"""Admin: who has which role, and which schedule each physician sees.

A role change takes effect at the user's next sign-in (their current token keeps the old role
until it expires). Admins can't change their own role, so the clinic always keeps an admin.
"""

from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, HTTPException, status

from app import db
from app.auth import Admin, AnyUser
from app.models import AdminUser, AdminUserUpdate, Provider

router = APIRouter()
Conn = Annotated[psycopg.Connection, Depends(db.get_conn)]

_USERS_SQL = """
    SELECT u.id, u.email, u.role, u.provider_id, p.name AS provider_name
    FROM users u LEFT JOIN providers p ON p.id = u.provider_id
"""


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
    """Change a role. A physician must be linked to a provider; other roles have none."""
    if user_id == admin.id:
        raise HTTPException(status.HTTP_409_CONFLICT, "You can't change your own role")
    if body.role == "physician" and body.provider_id is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Choose the schedule this physician sees"
        )
    provider_id = body.provider_id if body.role == "physician" else None
    if (
        provider_id is not None
        and not conn.execute("SELECT 1 FROM providers WHERE id = %s", (provider_id,)).fetchone()
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Provider not found")
    updated = conn.execute(
        "UPDATE users SET role = %s, provider_id = %s WHERE id = %s RETURNING id",
        (body.role, provider_id, user_id),
    ).fetchone()
    if updated is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return AdminUser(**conn.execute(_USERS_SQL + " WHERE u.id = %s", (user_id,)).fetchone())
