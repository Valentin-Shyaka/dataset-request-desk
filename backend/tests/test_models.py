from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.models import Assignment, DatasetRequest, Role, Status


def test_migration_seeds_known_robots(db):
    robots = set(db.scalars(text("SELECT id FROM robots")))
    assert robots == {"arm-01", "arm-02", "arm-03", "mobile-01", "humanoid-01"}


def test_database_rejects_invalid_quality(db, make_episode):
    with pytest.raises(IntegrityError):
        make_episode(quality="excellent")


def test_database_rejects_unknown_robot(db, make_episode):
    with pytest.raises(IntegrityError):
        make_episode(robot_id="arm-99")


def test_database_refuses_to_assign_one_episode_to_two_requests(db, make_user, make_episode):
    """The last line of defence against two operators racing: a UNIQUE constraint."""
    client = make_user(Role.CLIENT)
    operator = make_user(Role.OPERATOR)
    episode = make_episode()
    requests = [
        DatasetRequest(client_id=client.id, task_name="pick cup", episodes_requested=1,
                       deadline=date(2026, 12, 1), status=Status.IN_PROGRESS)
        for _ in range(2)
    ]
    db.add_all(requests)
    db.commit()
    db.add(Assignment(request_id=requests[0].id, episode_id=episode.episode_id, assigned_by_id=operator.id))
    db.commit()
    db.add(Assignment(request_id=requests[1].id, episode_id=episode.episode_id, assigned_by_id=operator.id))
    with pytest.raises(IntegrityError):
        db.commit()
