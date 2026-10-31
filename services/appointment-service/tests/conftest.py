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

# Dev-mode auth with a throwaway secret, so tests sign in with real tokens
os.environ["AUTH_MODE"] = "dev"
os.environ["AUTH_DEV_SECRET"] = "test-secret-for-pytest-only"

DB_DIR = Path(__file__).resolve().parent.parent / "db"
TEST_SCHEMA = "pytest_appointments"
TABLES = "lab_results, lab_reports, triage_results, appointments, slots, providers, users"


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
        # schema.sql, then the migrations (schemav2_..., ...) in order, like docker compose
        for path in sorted(DB_DIR.glob("schema*.sql")):
            conn.execute(path.read_text())
    return url


@pytest.fixture
def db(database_url: str):
    """A connection to an empty copy of the schema."""
    with _connect(database_url) as conn:
        conn.execute(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE")
        yield conn


@pytest.fixture
def client(database_url: str, db):
    """API client whose requests use the empty test schema instead of DATABASE_URL."""
    from fastapi.testclient import TestClient
    from psycopg.rows import dict_row

    from app import db as app_db
    from app.main import app

    def test_conn():
        with _connect(database_url) as conn:
            conn.row_factory = dict_row
            yield conn

    app.dependency_overrides[app_db.get_conn] = test_conn
    yield TestClient(app)
    app.dependency_overrides.clear()


def as_user(user_id: int, role: str = "patient", email: str | None = None) -> dict[str, str]:
    """Authorization header for a user that exists in the test database."""
    from app.auth import CurrentUser, issue_dev_token

    token = issue_dev_token(CurrentUser(user_id, email or f"user{user_id}@example.com", role))
    return {"Authorization": f"Bearer {token}"}
