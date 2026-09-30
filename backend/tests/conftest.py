import itertools
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

# Must be set before `app` is imported, because app.config reads env vars at import time.
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://drd:drd@localhost:5432/drd_test")
os.environ.setdefault("BCRYPT_ROUNDS", "4")  # fast hashing in tests only

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from app.db import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Episode, Role, User  # noqa: E402
from app.security import hash_password  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parent.parent
PASSWORD = "correct-horse-battery"


def _create_database_if_missing(url_string: str) -> None:
    url = make_url(url_string)
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.scalar(text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": url.database})
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    admin.dispose()


@pytest.fixture(scope="session", autouse=True)
def migrated_database():
    """Build the schema with the real migrations, down then up, so both directions are exercised."""
    _create_database_if_missing(os.environ["DATABASE_URL"])
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")


@pytest.fixture(autouse=True)
def clean_tables():
    # robots is reference data seeded by the migration, so it is kept.
    with engine.begin() as conn:
        conn.execute(text(
            "TRUNCATE request_status_events, assignments, dataset_requests, episodes, users "
            "RESTART IDENTITY CASCADE"
        ))


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session


@pytest.fixture
def make_user(db):
    def _make(role: Role, email: str | None = None, name: str = "Test User", is_active: bool = True) -> User:
        user = User(
            email=email or f"{role}-{uuid.uuid4().hex[:8]}@example.com",
            name=name,
            role=role,
            password_hash=hash_password(PASSWORD),
            is_active=is_active,
        )
        db.add(user)
        db.commit()
        return user
    return _make


@pytest.fixture
def make_episode(db):
    counter = itertools.count(1)

    def _make(**overrides) -> Episode:
        values = {
            "episode_id": f"EP-{next(counter):05d}",
            "robot_id": "arm-01",
            "task_name": "pick cup",
            "recorded_at": datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
            "duration_seconds": 30,
            "operator_name": "Aline",
            "quality": "good",
        } | overrides
        episode = Episode(**values)
        db.add(episode)
        db.commit()
        return episode
    return _make


@pytest.fixture
def anon():
    return TestClient(app)


@pytest.fixture
def login():
    """Returns a TestClient logged in as `user`. Each client has its own cookie jar."""
    def _login(user: User) -> TestClient:
        client = TestClient(app)
        response = client.post("/api/auth/login", json={"email": user.email, "password": PASSWORD})
        assert response.status_code == 200, response.text
        return client
    return _login
