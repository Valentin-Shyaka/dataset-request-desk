"""Database tables. The Alembic migration is what actually creates the schema;
these classes mirror it so the ORM knows the shape."""
import enum
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Role(enum.StrEnum):
    CLIENT = "client"
    OPERATOR = "operator"
    ADMIN = "admin"


STAFF_ROLES = (Role.OPERATOR, Role.ADMIN)


class Quality(enum.StrEnum):
    GOOD = "good"
    USABLE = "usable"
    BAD = "bad"


ASSIGNABLE_QUALITIES = (Quality.GOOD, Quality.USABLE)


class Status(enum.StrEnum):
    SUBMITTED = "submitted"
    IN_PROGRESS = "in_progress"
    DELIVERED = "delivered"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("role IN ('client', 'operator', 'admin')", name="ck_users_role"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    organisation: Mapped[str | None] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20))
    password_hash: Mapped[str] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Robot(Base):
    __tablename__ = "robots"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)


class Episode(Base):
    __tablename__ = "episodes"
    __table_args__ = (
        CheckConstraint("quality IN ('good', 'usable', 'bad')", name="ck_episodes_quality"),
        CheckConstraint("duration_seconds > 0", name="ck_episodes_duration_positive"),
        Index("ix_episodes_recorded_at_robot", "recorded_at", "robot_id"),
        Index("ix_episodes_task_quality", "task_name", "quality"),
        Index("ix_episodes_good_recorded_task", "recorded_at", "task_name",
              postgresql_where=text("quality = 'good'")),
    )

    episode_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    robot_id: Mapped[str] = mapped_column(String(50), ForeignKey("robots.id"))
    task_name: Mapped[str] = mapped_column(String(200))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[int]
    operator_name: Mapped[str | None] = mapped_column(String(200))
    quality: Mapped[str] = mapped_column(String(10))
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DatasetRequest(Base):
    __tablename__ = "dataset_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('submitted', 'in_progress', 'delivered', 'accepted', 'rejected')",
            name="ck_dataset_requests_status",
        ),
        CheckConstraint("episodes_requested > 0", name="ck_dataset_requests_episodes_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    task_name: Mapped[str] = mapped_column(String(200))
    episodes_requested: Mapped[int]
    deadline: Mapped[date] = mapped_column(Date)
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")
    status: Mapped[str] = mapped_column(String(20), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    client: Mapped[User] = relationship()
    events: Mapped[list["StatusEvent"]] = relationship(order_by="StatusEvent.id")
    assignments: Mapped[list["Assignment"]] = relationship(order_by="Assignment.episode_id")


class StatusEvent(Base):
    """Append-only audit log: one row per status change (including creation)."""

    __tablename__ = "request_status_events"
    __table_args__ = (Index("ix_status_events_to_status_request", "to_status", "request_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("dataset_requests.id"), index=True)
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str] = mapped_column(String(20))
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    actor: Mapped[User] = relationship()


class Assignment(Base):
    __tablename__ = "assignments"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("dataset_requests.id"), index=True)
    # unique=True *is* the rule "an episode can be assigned to at most one request at a time".
    # Postgres enforces it, so two operators racing to assign the same episode cannot both win.
    episode_id: Mapped[str] = mapped_column(String(50), ForeignKey("episodes.episode_id"), unique=True)
    assigned_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    episode: Mapped[Episode] = relationship()
