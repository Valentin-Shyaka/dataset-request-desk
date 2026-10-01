from datetime import UTC, datetime, timedelta

import pytest

from app.models import DatasetRequest, Role, Status, StatusEvent

T0 = datetime(2026, 8, 10, 9, 0, tzinfo=UTC)


@pytest.fixture
def staff(login, make_user):
    return login(make_user(Role.OPERATOR))


def get(client, frm="2026-08-01", to="2026-08-31"):
    return client.get("/api/analytics", params={"from": frm, "to": to})


def test_episodes_per_day_per_robot_respects_inclusive_range(staff, make_episode):
    make_episode(robot_id="arm-01", recorded_at=datetime(2026, 8, 1, 0, 0, tzinfo=UTC))
    make_episode(robot_id="arm-01", recorded_at=datetime(2026, 8, 1, 23, 59, tzinfo=UTC))
    make_episode(robot_id="arm-02", recorded_at=datetime(2026, 8, 1, 12, 0, tzinfo=UTC))
    make_episode(robot_id="arm-01", recorded_at=datetime(2026, 8, 31, 23, 59, 59, tzinfo=UTC))
    make_episode(robot_id="arm-01", recorded_at=datetime(2026, 9, 1, 0, 0, tzinfo=UTC))  # outside
    body = get(staff).json()
    assert body["episodes_per_day"] == [
        {"day": "2026-08-01", "robot_id": "arm-01", "episodes": 2},
        {"day": "2026-08-01", "robot_id": "arm-02", "episodes": 1},
        {"day": "2026-08-31", "robot_id": "arm-01", "episodes": 1},
    ]


def test_top_five_tasks_by_good_episodes(staff, make_episode):
    for task, good in [("a", 6), ("b", 5), ("c", 4), ("d", 3), ("e", 2), ("f", 1)]:
        for _ in range(good):
            make_episode(task_name=task, quality="good")
    for _ in range(10):
        make_episode(task_name="f", quality="usable")  # usable doesn't count
    top = get(staff).json()["top_tasks_by_good_episodes"]
    assert [(t["task_name"], t["good_episodes"]) for t in top] == [("a", 6), ("b", 5), ("c", 4), ("d", 3), ("e", 2)]


def test_request_counts_and_median_time_to_first_delivery(staff, db, make_user):
    client = make_user(Role.CLIENT)
    operator = make_user(Role.OPERATOR)

    def request_delivered_after(hours, final_status=Status.ACCEPTED):
        req = DatasetRequest(client_id=client.id, task_name="t", episodes_requested=1,
                             deadline=T0.date(), status=final_status, created_at=T0)
        db.add(req)
        db.flush()
        if hours is not None:
            db.add(StatusEvent(request_id=req.id, from_status="in_progress", to_status="delivered",
                               actor_id=operator.id, created_at=T0 + timedelta(hours=hours)))
            # a later re-delivery must not change the result: we measure the *first* delivery
            db.add(StatusEvent(request_id=req.id, from_status="in_progress", to_status="delivered",
                               actor_id=operator.id, created_at=T0 + timedelta(hours=hours + 100)))
        db.commit()

    request_delivered_after(1)
    request_delivered_after(3)
    request_delivered_after(10, final_status=Status.DELIVERED)
    request_delivered_after(None, final_status=Status.SUBMITTED)

    body = get(staff).json()
    assert body["requests_by_status"] == {"submitted": 1, "in_progress": 0, "delivered": 1,
                                          "accepted": 2, "rejected": 0}
    assert body["median_seconds_submitted_to_delivered"] == 3 * 3600


def test_empty_range_returns_zeros_not_errors(staff):
    body = get(staff, "2030-01-01", "2030-01-31").json()
    assert body["episodes_per_day"] == [] and body["top_tasks_by_good_episodes"] == []
    assert set(body["requests_by_status"].values()) == {0}
    assert body["median_seconds_submitted_to_delivered"] is None


def test_invalid_range_and_permissions(staff, login, make_user):
    assert get(staff, "2026-08-31", "2026-08-01").status_code == 422
    assert get(login(make_user(Role.CLIENT))).status_code == 403
