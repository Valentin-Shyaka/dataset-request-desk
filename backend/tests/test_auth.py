import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt
import pytest

from app.config import settings
from app.deps import COOKIE_NAME
from app.models import Role, User
from app.seed import seed_users
from app.security import verify_password
from tests.conftest import PASSWORD

SEED_FILE = Path(__file__).resolve().parents[2] / "seed" / "users.json"


def test_login_sets_httponly_cookie_and_returns_user(anon, make_user):
    user = make_user(Role.CLIENT, email="c@example.com")
    response = anon.post("/api/auth/login", json={"email": "C@Example.com ", "password": PASSWORD})
    assert response.status_code == 200
    assert response.json()["email"] == "c@example.com"
    assert "password_hash" not in response.json()
    cookie_header = response.headers["set-cookie"].lower()
    assert COOKIE_NAME in cookie_header and "httponly" in cookie_header and "samesite=strict" in cookie_header


@pytest.mark.parametrize("email,password", [
    ("c@example.com", "wrong-password"),
    ("nobody@example.com", PASSWORD),
    ("c@example.com", "x" * 100),  # longer than bcrypt's 72-byte limit: must be a 401, not a 500
])
def test_bad_credentials_get_the_same_401(anon, make_user, email, password):
    make_user(Role.CLIENT, email="c@example.com")
    response = anon.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password"


def test_inactive_user_cannot_log_in(anon, make_user):
    make_user(Role.CLIENT, email="c@example.com", is_active=False)
    response = anon.post("/api/auth/login", json={"email": "c@example.com", "password": PASSWORD})
    assert response.status_code == 401


def test_me_requires_authentication(anon):
    assert anon.get("/api/auth/me").status_code == 401


def test_me_returns_current_user(login, make_user):
    user = make_user(Role.OPERATOR)
    assert login(user).get("/api/auth/me").json()["id"] == user.id


def test_forged_and_expired_tokens_are_rejected(anon, make_user):
    user = make_user(Role.ADMIN)
    now = datetime.now(UTC)
    forged = jwt.encode({"sub": str(user.id), "exp": now + timedelta(hours=1)}, "an-attacker-guessed-secret-of-32-plus-bytes", algorithm="HS256")
    expired = jwt.encode({"sub": str(user.id), "exp": now - timedelta(minutes=1)}, settings.jwt_secret, algorithm="HS256")
    for token in (forged, expired, "garbage"):
        anon.cookies.set(COOKIE_NAME, token)
        assert anon.get("/api/auth/me").status_code == 401


def test_deactivation_takes_effect_on_existing_session(login, make_user, db):
    user = make_user(Role.OPERATOR)
    client = login(user)
    db.get(User, user.id).is_active = False
    db.commit()
    assert client.get("/api/auth/me").status_code == 401


def test_logout_clears_cookie(login, make_user):
    client = login(make_user(Role.CLIENT))
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 401


def test_access_log_includes_user_id_when_authenticated(login, make_user, caplog):
    user = make_user(Role.CLIENT)
    client = login(user)
    with caplog.at_level(logging.INFO, logger="drd.access"):
        client.get("/api/auth/me")
    [record] = [r for r in caplog.records if r.name == "drd.access"]
    assert record.fields["user_id"] == user.id


def test_seed_users_hashes_passwords_and_is_idempotent(db):
    assert seed_users(db, SEED_FILE) == 5
    assert seed_users(db, SEED_FILE) == 0
    admin = db.query(User).filter_by(email="admin@example.com").one()
    assert admin.role == Role.ADMIN
    assert admin.password_hash != "admin123" and admin.password_hash.startswith("$2")
    assert verify_password("admin123", admin.password_hash)
