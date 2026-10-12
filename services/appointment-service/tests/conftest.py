"""Shared test fixtures.

Database tests need a PostgreSQL server. Point TEST_DATABASE_URL at one, for example the
compose database:

    docker compose up -d db
    TEST_DATABASE_URL=postgresql://clinic:local_dev_password_change_me@localhost:5432/clinic pytest

The tests only touch their own schema (TEST_SCHEMA), which is dropped and recreated on every
run, so the dev data in "public" is left alone. Without TEST_DATABASE_URL, database tests are
skipped. CI always sets it.
"""

import os
from pathlib import Path

import psycopg
import pytest

DB_DIR = Path(__file__).resolve().parent.parent / "db"
TEST_SCHEMA = "pytest_appointments"
TABLES = "triage_results, appointments, slots, providers, users"


def _connect(url: str) -> psycopg.Connection:
    return psycopg.connect(url, autocommit=True, options=f"-c search_path={TEST_SCHEMA}")


@pytest.fixture(scope="session")
def database_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set")
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(f"DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE")
        conn.execute(f"CREATE SCHEMA {TEST_SCHEMA}")
    with _connect(url) as conn:
        conn.execute((DB_DIR / "schema.sql").read_text())
    return url


@pytest.fixture
def db(database_url: str):
    """A connection to an empty copy of the schema."""
    with _connect(database_url) as conn:
        conn.execute(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE")
        yield conn
