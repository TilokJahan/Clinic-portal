"""Admin: invitations, roles, and which accounts may sign in.

The admin invites someone by email with a role (and, for a physician, the schedule they see).
The app makes a personal invite link; the admin sends it from their own email (the portal has
no email service). Whoever opens the link registers with that role: in the demo by accepting
it, with Entra External ID by signing up with the invited email, which applies the invitation
at their first sign-in.

Roles and the active flag are read from the database on every request (app/auth.py), so a
change applies at once, and a disabled account can't use a token it already has. Admins can't
change or disable their own account, so the clinic always keeps an admin.
"""

import secrets
from datetime import datetime
from typing import Annotated, Literal

import psycopg
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from app import db
from app.auth import Admin, AnyUser, CurrentUser, auth_mode, issue_dev_token
from app.models import AdminUser, AdminUserUpdate, Provider, TokenResponse, UserOut

router = APIRouter()
Conn = Annotated[psycopg.Connection, Depends(db.get_conn)]

INVITE_DAYS = 7
Role = Literal["patient", "clinician", "physician", "admin", "lab_tech"]

_USERS_SQL = """
    SELECT u.id, u.email, u.role, u.provider_id, p.name AS provider_name, u.active
    FROM users u LEFT JOIN providers p ON p.id = u.provider_id
"""


class InvitationCreate(BaseModel):
    email: str = Field(min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    role: Role
    provider_id: int | None = Field(default=None, gt=0)

    @field_validator("email", mode="before")
    @classmethod
    def tidy(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value


class Invitation(BaseModel):
    id: int
    email: str
    role: Role
    provider_id: int | None
    provider_name: str | None
    created_at: datetime
    expires_at: datetime
    status: Literal["pending", "accepted", "expired", "revoked"]
    # The path of the invite link (the frontend adds its own origin); only while pending
    link: str | None = None


class InvitationView(BaseModel):
    """What the person who opens the link sees: who it's for and as what. No other details."""

    email: str
    role: Role
    provider_name: str | None
    status: Literal["pending", "accepted", "expired", "revoked"]
    expires_at: datetime
    # How to accept: "accept" (demo sign-in) or "sign_up" (Entra External ID)
    method: Literal["accept", "sign_up"]


_INVITES_SQL = """
    SELECT i.id, i.email, i.role, i.provider_id, p.name AS provider_name, i.created_at,
           i.expires_at, i.token,
           CASE WHEN i.revoked_at IS NOT NULL THEN 'revoked'
                WHEN i.accepted_at IS NOT NULL THEN 'accepted'
                WHEN i.expires_at <= now() THEN 'expired'
                ELSE 'pending' END AS status
    FROM invitations i LEFT JOIN providers p ON p.id = i.provider_id
"""


def _invitation(row: dict) -> Invitation:
    link = f"/invite/{row['token']}" if row["status"] == "pending" else None
    return Invitation(**{k: v for k, v in row.items() if k != "token"}, link=link)


def _check_provider(conn: psycopg.Connection, role: str, provider_id: int | None) -> int | None:
    if role == "physician" and provider_id is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Choose the schedule this physician sees"
        )
    provider_id = provider_id if role == "physician" else None
    if (
        provider_id is not None
        and not conn.execute("SELECT 1 FROM providers WHERE id = %s", (provider_id,)).fetchone()
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Provider not found")
    return provider_id


def apply_invitation(conn: psycopg.Connection, user_id: int, email: str) -> None:
    """Give a user the role of their pending invitation (the newest one), once."""
    invite = conn.execute(
        """
        SELECT id, role, provider_id FROM invitations
        WHERE email = %s AND accepted_at IS NULL AND revoked_at IS NULL AND expires_at > now()
        ORDER BY created_at DESC LIMIT 1
        """,
        (email,),
    ).fetchone()
    if invite is None:
        return
    conn.execute(
        "UPDATE users SET role = %s, provider_id = %s, active = true WHERE id = %s",
        (invite["role"], invite["provider_id"], user_id),
    )
    conn.execute(
        "UPDATE invitations SET accepted_at = now(), accepted_user_id = %s WHERE id = %s",
        (user_id, invite["id"]),
    )


# --- Users -------------------------------------------------------------------------------------


@router.get("/providers")
def providers(conn: Conn, _: AnyUser) -> list[Provider]:
    """The doctors whose schedules can be booked."""
    rows = conn.execute("SELECT id, name, specialty FROM providers ORDER BY name").fetchall()
    return [Provider(**row) for row in rows]


@router.get("/admin/users")
def list_users(conn: Conn, _: Admin) -> list[AdminUser]:
    """Every account: staff first (by role), then patients."""
    rows = conn.execute(
        _USERS_SQL
        + """
        ORDER BY CASE u.role WHEN 'admin' THEN 0 WHEN 'physician' THEN 1 WHEN 'clinician' THEN 2
                 WHEN 'lab_tech' THEN 3 ELSE 4 END, u.id
        """
    ).fetchall()
    return [AdminUser(**row) for row in rows]


@router.patch("/admin/users/{user_id}")
def update_user(conn: Conn, admin: Admin, user_id: int, body: AdminUserUpdate) -> AdminUser:
    """Change a role (a physician must be linked to a provider), or disable or enable the
    account. Takes effect at once."""
    if user_id == admin.id:
        raise HTTPException(status.HTTP_409_CONFLICT, "You can't change your own account")
    provider_id = _check_provider(conn, body.role, body.provider_id)
    updated = conn.execute(
        """
        UPDATE users SET role = %s, provider_id = %s, active = coalesce(%s, active)
        WHERE id = %s RETURNING id
        """,
        (body.role, provider_id, body.active, user_id),
    ).fetchone()
    if updated is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return AdminUser(**conn.execute(_USERS_SQL + " WHERE u.id = %s", (user_id,)).fetchone())


# --- Invitations -------------------------------------------------------------------------------


@router.post("/admin/invitations", status_code=status.HTTP_201_CREATED)
def invite(conn: Conn, admin: Admin, body: InvitationCreate) -> Invitation:
    """Invite someone by email with a role. Returns the invite link to send them; it works
    once, for 7 days. A newer invitation for the same email replaces an older pending one."""
    email = body.email.strip().lower()
    if email == admin.email.lower():
        raise HTTPException(status.HTTP_409_CONFLICT, "You can't invite yourself")
    provider_id = _check_provider(conn, body.role, body.provider_id)
    with conn.transaction():
        conn.execute(
            "UPDATE invitations SET revoked_at = now() "
            "WHERE email = %s AND accepted_at IS NULL AND revoked_at IS NULL",
            (email,),
        )
        new_id = conn.execute(
            f"""
            INSERT INTO invitations (email, role, provider_id, token, invited_by, expires_at)
            VALUES (%s, %s, %s, %s, %s, now() + interval '{INVITE_DAYS} days')
            RETURNING id
            """,
            (email, body.role, provider_id, secrets.token_urlsafe(24), admin.id),
        ).fetchone()["id"]
    return _invitation(conn.execute(_INVITES_SQL + " WHERE i.id = %s", (new_id,)).fetchone())


@router.get("/admin/invitations")
def list_invitations(conn: Conn, _: Admin) -> list[Invitation]:
    """Invitations, newest first (the last 100)."""
    rows = conn.execute(_INVITES_SQL + " ORDER BY i.created_at DESC LIMIT 100").fetchall()
    return [_invitation(row) for row in rows]


@router.post("/admin/invitations/{invitation_id}/revoke")
def revoke(conn: Conn, _: Admin, invitation_id: int) -> Invitation:
    """Withdraw a pending invitation; its link stops working."""
    done = conn.execute(
        "UPDATE invitations SET revoked_at = now() "
        "WHERE id = %s AND accepted_at IS NULL AND revoked_at IS NULL RETURNING id",
        (invitation_id,),
    ).fetchone()
    if done is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pending invitation not found")
    return _invitation(conn.execute(_INVITES_SQL + " WHERE i.id = %s", (invitation_id,)).fetchone())


# --- Opening an invite link (no sign-in needed: the link is the secret) ------------------------


def _by_token(conn: psycopg.Connection, token: str) -> dict:
    row = conn.execute(_INVITES_SQL + " WHERE i.token = %s", (token,)).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This invitation link isn't valid")
    return row


@router.get("/invitations/{token}")
def view_invitation(conn: Conn, token: str) -> InvitationView:
    row = _by_token(conn, token)
    method = "accept" if auth_mode() == "dev" else "sign_up"
    return InvitationView(
        **{k: row[k] for k in InvitationView.model_fields if k != "method"}, method=method
    )


@router.post("/invitations/{token}/accept")
def accept_invitation(conn: Conn, token: str) -> TokenResponse:
    """Register with the invitation's email and role and sign in (demo sign-in). With Entra
    External ID, signing up with the invited email does this instead."""
    if auth_mode() != "dev":
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Sign up with the invited email address to accept"
        )
    with conn.transaction():
        row = _by_token(conn, token)
        if row["status"] != "pending":
            raise HTTPException(status.HTTP_409_CONFLICT, f"This invitation is {row['status']}")
        user = conn.execute(
            """
            INSERT INTO users (email, role) VALUES (%s, 'patient')
            ON CONFLICT (email) DO UPDATE SET email = excluded.email
            RETURNING id
            """,
            (row["email"],),
        ).fetchone()
        apply_invitation(conn, user["id"], row["email"])
        me = conn.execute(
            "SELECT id, email, role FROM users WHERE id = %s", (user["id"],)
        ).fetchone()
    current = CurrentUser(**me)
    return TokenResponse(access_token=issue_dev_token(current), user=UserOut(**me))
