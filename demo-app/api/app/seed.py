"""Seed the DB with sample products + users on startup if empty."""
from __future__ import annotations

import logging
from passlib.hash import bcrypt
from sqlalchemy import select

from .db import SessionLocal
from .models import Product, User

logger = logging.getLogger(__name__)


SAMPLE_PRODUCTS = [
    ("SKU-001", "Wireless Mouse",        "Ergonomic, USB-C charging",      "29.99",  120),
    ("SKU-002", "Mechanical Keyboard",   "Cherry MX brown, RGB",           "129.99", 50),
    ("SKU-003", "27-inch Monitor",       "QHD, 165Hz",                     "349.99", 30),
    ("SKU-004", "USB-C Hub",             "7-in-1 expansion",               "49.99",  200),
    ("SKU-005", "Webcam 1080p",          "Auto-focus, dual mic",           "79.99",  80),
    ("SKU-006", "Laptop Stand",          "Aluminium, adjustable",          "39.99",  150),
    ("SKU-007", "Headphones",            "ANC, 30h battery",                "199.99", 60),
    ("SKU-008", "Standing Desk Mat",     "Anti-fatigue",                   "59.99",  100),
]

SAMPLE_USERS = [
    ("alice",   "alice@example.com",  "password123"),
    ("bob",     "bob@example.com",    "password123"),
    ("carol",   "carol@example.com",  "password123"),
    ("dave",    "dave@example.com",   "password123"),
    ("eve",     "eve@example.com",    "password123"),
]


async def seed_if_empty() -> None:
    async with SessionLocal() as s:
        count = (await s.execute(select(Product))).scalars().first()
        if count is None:
            logger.info("Seeding products + users")
            for sku, name, desc, price, stock in SAMPLE_PRODUCTS:
                s.add(Product(sku=sku, name=name, description=desc, price=price, stock=stock))
            for uname, email, pw in SAMPLE_USERS:
                s.add(User(username=uname, email=email, password_hash=bcrypt.hash(pw)))
            await s.commit()
            logger.info("Seeded %d products + %d users", len(SAMPLE_PRODUCTS), len(SAMPLE_USERS))
        else:
            logger.info("DB already has data; skipping seed")
