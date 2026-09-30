import pytest

from app.models import Role
from tests.conftest import PASSWORD


@pytest.mark.parametrize("role", [Role.CLIENT, Role.OPERATOR])
def test_only_admins_can_manage_users(login, make_user, role):
    client = login(make_user(role))
    assert client.get("/api/users").status_code == 403
    assert client.post("/api/users", json={}).status_code in (403, 422)
    assert client.patch("/api/users/1", json={"is_active": False}).status_code == 403


def test_admin_creates_user_who_can_log_in(login, make_user, anon):
    admin = login(make_user(Role.ADMIN))
    response = admin.post("/api/users", json={
        "email": "New@Example.com", "name": "New Op", "role": "operator", "password": "s3cure-pass",
    })
    assert response.status_code == 201
    assert response.json()["email"] == "new@example.com"
    login_response = anon.post("/api/auth/login", json={"email": "new@example.com", "password": "s3cure-pass"})
    assert login_response.status_code == 200


def test_duplicate_email_is_a_conflict(login, make_user):
    make_user(Role.CLIENT, email="taken@example.com")
    admin = login(make_user(Role.ADMIN))
    response = admin.post("/api/users", json={
        "email": "taken@example.com", "name": "X", "role": "client", "password": "s3cure-pass",
    })
    assert response.status_code == 409


def test_short_password_rejected(login, make_user):
    admin = login(make_user(Role.ADMIN))
    response = admin.post("/api/users", json={"email": "a@b.co", "name": "X", "role": "client", "password": "short"})
    assert response.status_code == 422


def test_admin_changes_role_and_deactivates(login, make_user, anon):
    admin = login(make_user(Role.ADMIN))
    target = make_user(Role.CLIENT)
    assert admin.patch(f"/api/users/{target.id}", json={"role": "operator"}).json()["role"] == "operator"
    assert admin.patch(f"/api/users/{target.id}", json={"is_active": False}).json()["is_active"] is False
    response = anon.post("/api/auth/login", json={"email": target.email, "password": PASSWORD})
    assert response.status_code == 401


def test_admin_cannot_lock_themselves_out(login, make_user):
    me = make_user(Role.ADMIN)
    admin = login(me)
    assert admin.patch(f"/api/users/{me.id}", json={"is_active": False}).status_code == 400
    assert admin.patch(f"/api/users/{me.id}", json={"role": "client"}).status_code == 400
