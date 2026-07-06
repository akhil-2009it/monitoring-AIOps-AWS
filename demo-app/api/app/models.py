"""SQLAlchemy ORM models for the demo e-commerce app."""
from __future__ import annotations

from datetime import datetime
from sqlalchemy import Column, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import relationship

from .db import Base


class Product(Base):
    __tablename__ = "products"
    id          = Column(Integer, primary_key=True, autoincrement=True)
    sku         = Column(String(64), unique=True, index=True, nullable=False)
    name        = Column(String(255), nullable=False)
    description = Column(String(1024))
    price       = Column(Numeric(10, 2), nullable=False)
    stock       = Column(Integer, default=0)
    created_at  = Column(DateTime, default=datetime.utcnow)


class User(Base):
    __tablename__ = "users"
    id            = Column(Integer, primary_key=True, autoincrement=True)
    username      = Column(String(64), unique=True, index=True, nullable=False)
    email         = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    failed_logins = Column(Integer, default=0)
    created_at    = Column(DateTime, default=datetime.utcnow)


class Order(Base):
    __tablename__ = "orders"
    id          = Column(Integer, primary_key=True, autoincrement=True)
    user_id     = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    total       = Column(Numeric(10, 2), nullable=False)
    status      = Column(String(32), default="pending", index=True)
    payment_method = Column(String(32), nullable=False)
    created_at  = Column(DateTime, default=datetime.utcnow, index=True)
    items       = relationship("OrderItem", back_populates="order", cascade="all,delete")


class OrderItem(Base):
    __tablename__ = "order_items"
    id         = Column(Integer, primary_key=True, autoincrement=True)
    order_id   = Column(Integer, ForeignKey("orders.id"), index=True, nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    quantity   = Column(Integer, nullable=False, default=1)
    unit_price = Column(Numeric(10, 2), nullable=False)
    order      = relationship("Order", back_populates="items")
