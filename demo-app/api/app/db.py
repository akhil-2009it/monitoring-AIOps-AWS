"""Database wiring (MySQL via SQLAlchemy async).

Schema is created at startup (idempotent). For a real app you'd use Alembic
migrations.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base


def _build_url() -> str:
    user = os.getenv("DB_USER", "demo")
    pw   = os.getenv("DB_PASSWORD", "demo")
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "3306")
    name = os.getenv("DB_NAME", "demoapp")
    return f"mysql+aiomysql://{user}:{pw}@{host}:{port}/{name}"


engine = create_async_engine(
    _build_url(),
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    pool_recycle=3600,
    echo=False,
)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()


async def init_schema() -> None:
    """Create tables if missing. Idempotent."""
    from .models import Product, User, Order, OrderItem  # noqa: F401  side-effect register
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@asynccontextmanager
async def session():
    async with SessionLocal() as s:
        yield s
