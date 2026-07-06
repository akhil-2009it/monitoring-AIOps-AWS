"""HTTP routes for the demo e-commerce API.

Realistic shape:
  GET  /products              browse
  GET  /products/{id}          product detail
  POST /login                  trigger auth (used by attack-mode brute force)
  POST /cart                   add to cart (in-process; not persistent for demo)
  POST /orders                 checkout
  GET  /orders/{id}            order detail
  POST /admin/seed             dev-only re-seed
  GET  /healthz, /metrics      probes + scrape

Each handler does:
  - Real-ish DB calls (so MySQL slow-query log captures something)
  - Random latency variance + occasional simulated 500
  - Structured logging with request_id + trace_id
"""
from __future__ import annotations

import asyncio
import logging
import os
import random
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from passlib.hash import bcrypt
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from .db import session
from .models import Order, OrderItem, Product, User
from .observability import (
    DB_QUERY_LATENCY,
    LOGIN_ATTEMPTS,
    ORDERS_PLACED,
    REQUEST_LATENCY,
)

router = APIRouter()
logger = logging.getLogger(__name__)


# Inject realism: probability of a synthetic 500, slow query, etc.
ERROR_RATE   = float(os.getenv("DEMO_ERROR_RATE",   "0.02"))   # 2 % default
SLOW_RATE    = float(os.getenv("DEMO_SLOW_RATE",    "0.05"))   # 5 %
SLOW_LATENCY = float(os.getenv("DEMO_SLOW_LATENCY", "1.5"))    # seconds


async def _get_session() -> AsyncSession:
    async with session() as s:
        yield s


async def _maybe_inject_chaos() -> None:
    """Realism: occasionally errors, occasionally slow."""
    if random.random() < ERROR_RATE:
        raise HTTPException(500, "synthetic 500 — chaos injection")
    if random.random() < SLOW_RATE:
        await asyncio.sleep(SLOW_LATENCY)


# ─── Schemas ──────────────────────────────────────────────────────────────────

class ProductOut(BaseModel):
    id: int; sku: str; name: str; description: str | None = None
    price: float; stock: int


class CartItem(BaseModel):
    product_id: int
    quantity: int = Field(default=1, ge=1, le=20)


class OrderIn(BaseModel):
    user_id: int
    items: list[CartItem]
    payment_method: str = "card"


class OrderOut(BaseModel):
    id: int; user_id: int; total: float; status: str
    payment_method: str; created_at: datetime
    items: list[dict]


class LoginIn(BaseModel):
    username: str; password: str


# ─── Routes ──────────────────────────────────────────────────────────────────

@router.get("/products", response_model=list[ProductOut])
async def list_products(s: AsyncSession = Depends(_get_session)) -> list[ProductOut]:
    await _maybe_inject_chaos()
    t0 = time.perf_counter()
    rows = (await s.execute(select(Product).order_by(Product.id))).scalars().all()
    DB_QUERY_LATENCY.labels(query="list_products").observe(time.perf_counter() - t0)
    return [ProductOut(id=p.id, sku=p.sku, name=p.name, description=p.description,
                       price=float(p.price), stock=p.stock) for p in rows]


@router.get("/products/{product_id}", response_model=ProductOut)
async def get_product(product_id: int, s: AsyncSession = Depends(_get_session)) -> ProductOut:
    await _maybe_inject_chaos()
    p = (await s.execute(select(Product).where(Product.id == product_id))).scalars().first()
    if p is None:
        raise HTTPException(404, "not found")
    return ProductOut(id=p.id, sku=p.sku, name=p.name, description=p.description,
                      price=float(p.price), stock=p.stock)


@router.post("/login")
async def login(body: LoginIn, request: Request, s: AsyncSession = Depends(_get_session)) -> dict:
    """Auth endpoint. Used by the attack-mode brute-force traffic generator."""
    await _maybe_inject_chaos()
    t0 = time.perf_counter()
    u = (await s.execute(select(User).where(User.username == body.username))).scalars().first()
    DB_QUERY_LATENCY.labels(query="login_lookup").observe(time.perf_counter() - t0)

    src_ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "?")

    if u is None:
        LOGIN_ATTEMPTS.labels(status="user_not_found").inc()
        logger.warning("login failed: user_not_found username=%r src_ip=%s", body.username, src_ip)
        # NB: same response for "user not found" and "wrong password" prevents enumeration.
        raise HTTPException(401, "invalid credentials")

    if not bcrypt.verify(body.password, u.password_hash):
        u.failed_logins += 1
        await s.commit()
        LOGIN_ATTEMPTS.labels(status="wrong_password").inc()
        logger.warning("login failed: wrong_password username=%r src_ip=%s failed_logins=%d",
                        body.username, src_ip, u.failed_logins)
        raise HTTPException(401, "invalid credentials")

    u.failed_logins = 0
    await s.commit()
    LOGIN_ATTEMPTS.labels(status="success").inc()
    logger.info("login success username=%r src_ip=%s", body.username, src_ip)
    # Toy session token. A real app would issue JWT or set a Cognito-issued cookie.
    return {"user_id": u.id, "username": u.username, "session": f"sess_{u.id}_{int(time.time())}"}


@router.post("/orders", response_model=OrderOut)
async def place_order(body: OrderIn, s: AsyncSession = Depends(_get_session)) -> OrderOut:
    await _maybe_inject_chaos()
    if not body.items:
        raise HTTPException(400, "no items")

    t0 = time.perf_counter()
    user = (await s.execute(select(User).where(User.id == body.user_id))).scalars().first()
    if user is None:
        raise HTTPException(404, "unknown user")

    items_payload = []
    total = 0.0
    for it in body.items:
        p = (await s.execute(select(Product).where(Product.id == it.product_id))).scalars().first()
        if p is None or p.stock < it.quantity:
            raise HTTPException(400, f"product {it.product_id} unavailable")
        p.stock -= it.quantity
        line_total = float(p.price) * it.quantity
        total += line_total
        items_payload.append({"product_id": p.id, "quantity": it.quantity, "unit_price": float(p.price)})

    order = Order(user_id=user.id, total=total, status="confirmed", payment_method=body.payment_method)
    s.add(order)
    await s.flush()
    for it in body.items:
        s.add(OrderItem(order_id=order.id, product_id=it.product_id,
                         quantity=it.quantity, unit_price=items_payload[0]["unit_price"]))
    await s.commit()

    DB_QUERY_LATENCY.labels(query="place_order").observe(time.perf_counter() - t0)
    ORDERS_PLACED.labels(payment_method=body.payment_method).inc()
    logger.info("order placed order_id=%d user_id=%d total=%.2f payment=%s",
                 order.id, user.id, total, body.payment_method)

    return OrderOut(id=order.id, user_id=user.id, total=total, status=order.status,
                     payment_method=order.payment_method, created_at=order.created_at,
                     items=items_payload)


@router.get("/orders/{order_id}", response_model=OrderOut)
async def get_order(order_id: int, s: AsyncSession = Depends(_get_session)) -> OrderOut:
    await _maybe_inject_chaos()
    o = (await s.execute(select(Order).where(Order.id == order_id))).scalars().first()
    if o is None:
        raise HTTPException(404, "not found")
    items = (await s.execute(select(OrderItem).where(OrderItem.order_id == o.id))).scalars().all()
    return OrderOut(id=o.id, user_id=o.user_id, total=float(o.total),
                     status=o.status, payment_method=o.payment_method, created_at=o.created_at,
                     items=[{"product_id": i.product_id, "quantity": i.quantity,
                              "unit_price": float(i.unit_price)} for i in items])


@router.get("/stats")
async def stats(s: AsyncSession = Depends(_get_session)) -> dict:
    """A quick aggregate to drive the MySQL slow-query log."""
    t0 = time.perf_counter()
    total_orders = (await s.execute(select(func.count(Order.id)))).scalar() or 0
    total_revenue = (await s.execute(select(func.coalesce(func.sum(Order.total), 0)))).scalar() or 0
    total_users = (await s.execute(select(func.count(User.id)))).scalar() or 0
    DB_QUERY_LATENCY.labels(query="stats").observe(time.perf_counter() - t0)
    return {
        "orders":   int(total_orders),
        "revenue":  float(total_revenue),
        "users":    int(total_users),
        "ts":       datetime.now(timezone.utc).isoformat(),
    }
