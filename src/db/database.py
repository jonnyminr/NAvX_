from __future__ import annotations

import os
from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SQLITE = ROOT / "data" / "navx.db"
DEFAULT_SQLITE.parent.mkdir(parents=True, exist_ok=True)

DATABASE_URL = (os.getenv("DATABASE_URL") or f"sqlite:///{DEFAULT_SQLITE.as_posix()}").strip()


class Base(DeclarativeBase):
    pass


def _build_engine(url: str) -> Engine:
    kwargs = {"pool_pre_ping": True, "future": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(url, **kwargs)


engine = _build_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def init_database() -> None:
    # Import models here so every mapped table is registered before create_all.
    from src.db import models  # noqa: F401

    Base.metadata.create_all(bind=engine)


def database_status() -> dict:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        backend = engine.url.get_backend_name()
        return {
            "configured": True,
            "reachable": True,
            "backend": backend,
            "persistent": backend != "sqlite" or str(engine.url.database) != ":memory:",
            "url_exposed": False,
        }
    except Exception as exc:
        return {
            "configured": bool(DATABASE_URL),
            "reachable": False,
            "backend": engine.url.get_backend_name() if engine else "unknown",
            "persistent": False,
            "url_exposed": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
