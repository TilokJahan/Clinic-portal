# ruff: noqa: F811  (pytest fixtures imported from other test modules)
"""Admin invitations, disabling accounts, and role changes that apply at once."""

from app.admin import apply_invitation
from tests.test_labs import lab_setup  # noqa: F401  (fixture)
from tests.test_roles_labs import ADMIN, CLINICIAN, PATIENT, world  # noqa: F401


def _invite(client, email="new.doctor@example.com", role="physician", provider_id=2, **kw):
    body = {"email": email, "role": role, "provider_id": provider_id, **kw}
    return client.post("/admin/invitations", json=body, headers=kw.pop("headers", ADMIN))


def _token(link):
    return link.rsplit("/", 1)[1]


def test_an_admin_invites_and_the_person_registers_with_that_role(client, world):
    response = _invite(client, email="  New.Doctor@Example.com ")
    assert response.status_code == 201
    invite = response.json()
    assert invite["email"] == "new.doctor@example.com" and invite["status"] == "pending"
    assert invite["link"].startswith("/invite/") and invite["provider_name"] == "Dr. Two"
    token = _token(invite["link"])
    # Opening the link needs no sign-in, and shows only who it's for and as what
    view = client.get(f"/invitations/{token}").json()
    assert view == {
        "email": "new.doctor@example.com",
        "role": "physician",
        "provider_name": "Dr. Two",
        "status": "pending",
        "expires_at": view["expires_at"],
        "method": "accept",
    }
    accepted = client.post(f"/invitations/{token}/accept")
    assert accepted.status_code == 200
    user = accepted.json()["user"]
    assert user["role"] == "physician"
    headers = {"Authorization": f"Bearer {accepted.json()['access_token']}"}
    assert client.get("/physician/schedule", headers=headers).status_code == 200
    # The link works once; the admin sees it accepted; dev sign-in now knows the account
    assert client.post(f"/invitations/{token}/accept").status_code == 409
    [listed] = client.get("/admin/invitations", headers=ADMIN).json()
    assert listed["status"] == "accepted" and listed["link"] is None
    login = client.post("/auth/dev-login", json={"email": "new.doctor@example.com"})
    assert login.status_code == 200


def test_invitations_are_checked(client, world):
    assert _invite(client, provider_id=None).status_code == 422  # a physician needs a schedule
    assert _invite(client, email="not-an-email").status_code == 422
    assert _invite(client, email="admin@example.com", role="clinician").status_code == 409
    assert (
        client.post(
            "/admin/invitations",
            json={"email": "x@example.com", "role": "clinician"},
            headers=CLINICIAN,
        ).status_code
        == 403
    )
    assert client.get("/invitations/not-a-real-token").status_code == 404


def test_a_new_invitation_replaces_the_old_one_and_can_be_revoked(client, world):
    first = _invite(client, email="nurse@example.com", role="clinician").json()
    second = _invite(client, email="nurse@example.com", role="lab_tech").json()
    assert client.post(f"/invitations/{_token(first['link'])}/accept").status_code == 409
    assert client.post(f"/admin/invitations/{second['id']}/revoke", headers=ADMIN).json()[
        "status"
    ] == ("revoked")
    assert client.get(f"/invitations/{_token(second['link'])}").json()["status"] == "revoked"
    assert client.post(f"/invitations/{_token(second['link'])}/accept").status_code == 409


def test_an_invitation_applies_at_first_sign_in_with_entra(client, world):
    """With Entra External ID the person signs up with the invited email; their first sign-in
    applies the invitation (app/auth.py calls apply_invitation)."""
    _invite(client, email="p2@example.com", role="clinician", provider_id=None)
    user_id = world.execute("SELECT id FROM users WHERE email = 'p2@example.com'").fetchone()[0]
    world.row_factory = __import__("psycopg").rows.dict_row
    apply_invitation(world, user_id, "p2@example.com")
    assert world.execute("SELECT role FROM users WHERE id = %s", (user_id,)).fetchone()["role"] == (
        "clinician"
    )


def test_disabling_an_account_stops_it_at_once(client, world):
    assert client.get("/appointments", headers=PATIENT).status_code == 200
    off = client.patch(
        "/admin/users/1", json={"role": "patient", "active": False}, headers=ADMIN
    ).json()
    assert off["active"] is False
    blocked = client.get("/appointments", headers=PATIENT)
    assert blocked.status_code == 403 and blocked.json()["detail"] == "This account is disabled"
    assert client.post("/auth/dev-login", json={"email": "p1@example.com"}).status_code == 403
    client.patch("/admin/users/1", json={"role": "patient", "active": True}, headers=ADMIN)
    assert client.get("/appointments", headers=PATIENT).status_code == 200


def test_a_role_change_applies_to_tokens_already_issued(client, world):
    client.patch("/admin/users/3", json={"role": "lab_tech"}, headers=ADMIN)
    # The clinician's token still says "clinician", but the database decides
    assert client.get("/me", headers=CLINICIAN).json()["role"] == "lab_tech"
    assert client.get("/queue", headers=CLINICIAN).status_code == 403
    assert client.patch("/admin/users/7", json={"role": "patient"}, headers=ADMIN).status_code == (
        409
    )
