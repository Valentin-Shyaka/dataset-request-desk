"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-09-30
"""
import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

KNOWN_ROBOTS = ["arm-01", "arm-02", "arm-03", "mobile-01", "humanoid-01"]


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("email", sa.String(254), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("organisation", sa.String(200)),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("password_hash", sa.String(100), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("role IN ('client', 'operator', 'admin')", name="ck_users_role"),
    )

    robots = op.create_table("robots", sa.Column("id", sa.String(50), primary_key=True))
    op.bulk_insert(robots, [{"id": robot} for robot in KNOWN_ROBOTS])

    op.create_table(
        "episodes",
        sa.Column("episode_id", sa.String(50), primary_key=True),
        sa.Column("robot_id", sa.String(50), sa.ForeignKey("robots.id"), nullable=False),
        sa.Column("task_name", sa.String(200), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_seconds", sa.Integer, nullable=False),
        sa.Column("operator_name", sa.String(200)),
        sa.Column("quality", sa.String(10), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("quality IN ('good', 'usable', 'bad')", name="ck_episodes_quality"),
        sa.CheckConstraint("duration_seconds > 0", name="ck_episodes_duration_positive"),
    )
    op.create_index("ix_episodes_recorded_at_robot", "episodes", ["recorded_at", "robot_id"])
    op.create_index("ix_episodes_task_quality", "episodes", ["task_name", "quality"])
    op.create_index(
        "ix_episodes_good_recorded_task", "episodes", ["recorded_at", "task_name"],
        postgresql_where=sa.text("quality = 'good'"),
    )

    op.create_table(
        "dataset_requests",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("client_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("task_name", sa.String(200), nullable=False),
        sa.Column("episodes_requested", sa.Integer, nullable=False),
        sa.Column("deadline", sa.Date, nullable=False),
        sa.Column("notes", sa.Text, nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('submitted', 'in_progress', 'delivered', 'accepted', 'rejected')",
            name="ck_dataset_requests_status",
        ),
        sa.CheckConstraint("episodes_requested > 0", name="ck_dataset_requests_episodes_positive"),
    )
    op.create_index("ix_dataset_requests_client_id", "dataset_requests", ["client_id"])
    op.create_index("ix_dataset_requests_status", "dataset_requests", ["status"])
    op.create_index("ix_dataset_requests_created_at", "dataset_requests", ["created_at"])

    op.create_table(
        "request_status_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("request_id", sa.Integer, sa.ForeignKey("dataset_requests.id"), nullable=False),
        sa.Column("from_status", sa.String(20)),
        sa.Column("to_status", sa.String(20), nullable=False),
        sa.Column("actor_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("note", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_request_status_events_request_id", "request_status_events", ["request_id"])
    op.create_index("ix_status_events_to_status_request", "request_status_events", ["to_status", "request_id"])

    op.create_table(
        "assignments",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("request_id", sa.Integer, sa.ForeignKey("dataset_requests.id"), nullable=False),
        sa.Column("episode_id", sa.String(50), sa.ForeignKey("episodes.episode_id"), nullable=False, unique=True),
        sa.Column("assigned_by_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_assignments_request_id", "assignments", ["request_id"])


def downgrade() -> None:
    op.drop_table("assignments")
    op.drop_table("request_status_events")
    op.drop_table("dataset_requests")
    op.drop_table("episodes")
    op.drop_table("robots")
    op.drop_table("users")
