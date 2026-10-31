import os
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

_pool: ConnectionPool | None = None
_url: str | None = None


def open_pool() -> None:
    """Create the connection pool from DATABASE_URL. Called once at app startup."""
    global _pool, _url
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    _url = url
    _pool = ConnectionPool(url, kwargs={"row_factory": dict_row}, open=True)


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def connection() -> Iterator[psycopg.Connection]:
    """A pooled connection for a short block of work outside a normal request."""
    if _pool is None:
        raise RuntimeError("Database pool is not open")
    with _pool.connection() as conn:
        yield conn


def get_conn() -> Iterator[psycopg.Connection]:
    """FastAPI dependency: one pooled connection per request."""
    if _pool is None:
        raise RuntimeError("Database pool is not open")
    with _pool.connection() as conn:
        yield conn


async def _connect_async() -> psycopg.AsyncConnection:
    if _url is None:
        raise RuntimeError("Database is not configured")
    return await psycopg.AsyncConnection.connect(_url, autocommit=True, row_factory=dict_row)


def get_async_connect():
    """FastAPI dependency: a factory for a dedicated async connection (used for LISTEN)."""
    return _connect_async
