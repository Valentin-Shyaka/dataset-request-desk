import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Role, User
from app.security import hash_password


def seed_users(db: Session, path: Path) -> int:
    """Create any users from the JSON file that don't exist yet. Existing users are left alone,
    so an admin's later changes (role, deactivation) survive a restart."""
    created = 0
    for entry in json.loads(path.read_text()):
        email = entry["email"].strip().lower()
        if db.scalar(select(User.id).where(User.email == email)) is not None:
            continue
        db.add(User(
            email=email,
            name=entry["name"],
            organisation=entry.get("organisation"),
            role=Role(entry["role"]),
            password_hash=hash_password(entry["password"]),
        ))
        created += 1
    db.commit()
    return created
