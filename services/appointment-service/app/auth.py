"""Authentication and role checks.

Two modes, chosen by AUTH_MODE:

- "dev" (local and docker compose): POST /auth/dev-login issues an HS256 token for one of the
  synthetic seed users, signed with AUTH_DEV_SECRET. No passwords: it is for demos only and is
  disabled in any other mode.
- "entra-external-id" (cloud): the frontend signs in with Microsoft Entra External ID (hosted
  sign-up/sign-in with email and password) and sends the ID token. We verify it against the
  tenant's public keys (RS256, issuer = the tenant, audience = ENTRA_CLIENT_ID), then look the
  user up by email. Emails listed in ADMIN_EMAILS or CLINICIAN_EMAILS (comma separated, set by
  operators) get that role; anyone else signing up becomes a patient.

Either way the endpoints only see a CurrentUser with our own users.id and role.
"""

import os
import time
from dataclasses import dataclass
from typing import Annotated

import jwt
import psycopg
from fastapi import Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app import db

ROLES = ("patient", "clinician", "admin")
DEV_TOKEN_SECONDS = 8 * 3600


@dataclass(frozen=True)
class CurrentUser:
    id: int
    email: str
    role: str


def auth_mode() -> str:
    return os.environ.get("AUTH_MODE", "dev").strip().lower()


def _dev_secret() -> str:
    secret = os.environ.get("AUTH_DEV_SECRET", "")
    if len(secret) < 16:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "AUTH_DEV_SECRET is not set")
    return secret


def issue_dev_token(user: CurrentUser) -> str:
    now = int(time.time())
    claims = {
        "sub": str(user.id),
        "email": user.email,
        "role": user.role,
        "iat": now,
        "exp": now + DEV_TOKEN_SECONDS,
    }
    return jwt.encode(claims, _dev_secret(), algorithm="HS256")


_jwks_client: jwt.PyJWKClient | None = None


def _verify_entra(token: str) -> dict:
    """Check an Entra External ID token: signature (tenant keys), issuer, audience, expiry."""
    global _jwks_client
    tenant_id = os.environ.get("ENTRA_TENANT_ID", "")
    subdomain = os.environ.get("ENTRA_TENANT_SUBDOMAIN", "")
    client_id = os.environ.get("ENTRA_CLIENT_ID", "")
    if not (tenant_id and subdomain and client_id):
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "ENTRA_TENANT_ID, ENTRA_TENANT_SUBDOMAIN and ENTRA_CLIENT_ID must be set",
        )
    if _jwks_client is None:
        _jwks_client = jwt.PyJWKClient(
            f"https://{subdomain}.ciamlogin.com/{tenant_id}/discovery/v2.0/keys", cache_keys=True
        )
    key = _jwks_client.get_signing_key_from_jwt(token)
    return jwt.decode(
        token,
        key.key,
        algorithms=["RS256"],
        audience=client_id,
        issuer=f"https://{tenant_id}.ciamlogin.com/{tenant_id}/v2.0",
    )


def _listed(variable: str) -> set[str]:
    return {e.strip().lower() for e in os.environ.get(variable, "").split(",") if e.strip()}


def _user_from_claims(conn: psycopg.Connection, claims: dict) -> CurrentUser:
    # The sign-up flow verifies the email address before the account exists. The address is in
    # "email" (optional claim) or, for email sign-in accounts, "preferred_username".
    email = (claims.get("email") or claims.get("preferred_username") or "").lower()
    if "@" not in email:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "The token has no email address")
    # Operator-controlled lists set staff roles, also for existing users (that's how staff are
    # added). Everyone else is created as a patient on first sign-in and keeps their role.
    configured = (
        "admin"
        if email in _listed("ADMIN_EMAILS")
        else "clinician"
        if email in _listed("CLINICIAN_EMAILS")
        else None
    )
    row = conn.execute(
        """
        INSERT INTO users (email, role) VALUES (%(email)s, %(role)s)
        ON CONFLICT (email) DO UPDATE
            SET role = coalesce(%(configured)s, users.role)
        RETURNING id, email, role
        """,
        {"email": email, "role": configured or "patient", "configured": configured},
    ).fetchone()
    return CurrentUser(**row)


def decode(token: str, conn: psycopg.Connection) -> CurrentUser:
    try:
        if auth_mode() == "dev":
            claims = jwt.decode(token, _dev_secret(), algorithms=["HS256"])
            return CurrentUser(id=int(claims["sub"]), email=claims["email"], role=claims["role"])
        if auth_mode() == "entra-external-id":
            return _user_from_claims(conn, _verify_entra(token))
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Unknown AUTH_MODE {auth_mode()!r}")


_bearer = HTTPBearer(auto_error=False)


def current_user(
    conn: Annotated[psycopg.Connection, Depends(db.get_conn)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    # EventSource can't send headers, so GET /queue/stream may pass the token as a query param
    access_token: Annotated[str | None, Query(include_in_schema=False)] = None,
) -> CurrentUser:
    token = credentials.credentials if credentials else access_token
    if not token:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Sign in required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return decode(token, conn)


def stream_clinician(
    access_token: Annotated[str | None, Query(include_in_schema=False)] = None,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
) -> CurrentUser:
    """Like require("clinician", "admin") for the long-lived SSE stream.

    Uses a short-lived connection for the lookup, so an open stream doesn't keep a pooled
    connection checked out for hours.
    """
    token = credentials.credentials if credentials else access_token
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in required")
    with db.connection() as conn:
        user = decode(token, conn)
    if user.role not in ("clinician", "admin"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed for your role")
    return user


def require(*roles: str):
    """Dependency factory: the signed-in user must have one of these roles."""

    def check(user: Annotated[CurrentUser, Depends(current_user)]) -> CurrentUser:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed for your role")
        return user

    return check


AnyUser = Annotated[CurrentUser, Depends(current_user)]
Patient = Annotated[CurrentUser, Depends(require("patient"))]
Clinician = Annotated[CurrentUser, Depends(require("clinician", "admin"))]
