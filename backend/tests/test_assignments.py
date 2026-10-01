from datetime import date, timedelta

import pytest

from app.models import Role

TOMORROW = (date.today() + timedelta(days=1)).isoformat()


@pytest.fixture
def setup(login, make_user):
    client = login(make_user(Role.CLIENT))
    operator = login(make_user(Role.OPERATOR))

    def new_request(count=2, start=True):
        req = client.post("/api/requests", json={"task_name": "pick cup", "episodes_requested": count,
                                                 "deadline": TOMORROW}).json()
        if start:
            assert operator.post(f"/api/requests/{req['id']}/transitions",
                                 json={"to_status": "in_progress"}).status_code == 200
        return req["id"]

    return client, operator, new_request


def assign(operator, request_id, *episode_ids):
    return operator.post(f"/api/requests/{request_id}/assignments", json={"episode_ids": list(episode_ids)})


def test_good_and_usable_episodes_can_be_assigned(setup, make_episode):
    _, operator, new_request = setup
    make_episode(episode_id="EP-00001", quality="good")
    make_episode(episode_id="EP-00002", quality="usable")
    response = assign(operator, new_request(), "EP-00001", "ep-00002")  # lowercase id is normalised
    assert response.status_code == 200
    assert response.json()["assigned_count"] == 2


def test_bad_episodes_cannot_be_assigned(setup, make_episode):
    _, operator, new_request = setup
    make_episode(episode_id="EP-00001", quality="good")
    make_episode(episode_id="EP-00002", quality="bad")
    request_id = new_request()
    response = assign(operator, request_id, "EP-00001", "EP-00002")
    assert response.status_code == 422 and "EP-00002" in response.json()["detail"]
    # all-or-nothing: the good one was not assigned either
    assert operator.get(f"/api/requests/{request_id}").json()["assigned_count"] == 0


def test_episode_can_only_belong_to_one_request_at_a_time(setup, make_episode):
    _, operator, new_request = setup
    make_episode(episode_id="EP-00001")
    first, second = new_request(), new_request()
    assert assign(operator, first, "EP-00001").status_code == 200
    response = assign(operator, second, "EP-00001")
    assert response.status_code == 409 and "EP-00001" in response.json()["detail"]
    # ...until it's unassigned from the first request
    assert operator.delete(f"/api/requests/{first}/assignments/EP-00001").status_code == 200
    assert assign(operator, second, "EP-00001").status_code == 200


def test_reassigning_to_the_same_request_is_a_no_op(setup, make_episode):
    _, operator, new_request = setup
    make_episode(episode_id="EP-00001")
    request_id = new_request()
    assign(operator, request_id, "EP-00001")
    assert assign(operator, request_id, "EP-00001").json()["assigned_count"] == 1


def test_unknown_episode_is_404(setup):
    _, operator, new_request = setup
    response = assign(operator, new_request(), "EP-99999")
    # check the message too: a missing *route* is also a 404
    assert response.status_code == 404 and "EP-99999" in response.json()["detail"]


def test_assignment_only_while_in_progress(setup, make_episode):
    _, operator, new_request = setup
    make_episode(episode_id="EP-00001")
    assert assign(operator, new_request(start=False), "EP-00001").status_code == 409


def test_clients_cannot_assign_or_list_episodes(setup, make_episode):
    client, _, new_request = setup
    make_episode(episode_id="EP-00001")
    assert assign(client, new_request(), "EP-00001").status_code == 403
    assert client.get("/api/episodes").status_code == 403


def test_cannot_deliver_until_enough_episodes_are_assigned(setup, make_episode):
    _, operator, new_request = setup
    make_episode(episode_id="EP-00001")
    make_episode(episode_id="EP-00002")
    request_id = new_request(count=2)
    assign(operator, request_id, "EP-00001")
    response = operator.post(f"/api/requests/{request_id}/transitions", json={"to_status": "delivered"})
    assert response.status_code == 409 and "1 of 2" in response.json()["detail"]
    assign(operator, request_id, "EP-00002")
    assert operator.post(f"/api/requests/{request_id}/transitions",
                         json={"to_status": "delivered"}).status_code == 200


def test_full_lifecycle_with_rejection_and_rework(setup, make_episode):
    client, operator, new_request = setup
    make_episode(episode_id="EP-00001")
    request_id = new_request(count=1)
    assign(operator, request_id, "EP-00001")

    def move(who, to, note=None):
        r = who.post(f"/api/requests/{request_id}/transitions", json={"to_status": to, "note": note})
        assert r.status_code == 200, r.text
        return r.json()

    move(operator, "delivered")
    assert assign(operator, request_id, "EP-00001").status_code == 409  # frozen once delivered
    move(client, "rejected", note="blurry video")
    move(operator, "in_progress")
    move(operator, "delivered")
    final = move(client, "accepted")
    assert [h["to_status"] for h in final["history"]] == \
        ["submitted", "in_progress", "delivered", "rejected", "in_progress", "delivered", "accepted"]
    assert final["history"][3]["note"] == "blurry video"
    assert final["allowed_transitions"] == []


def test_episode_list_filters(setup, make_episode):
    _, operator, new_request = setup
    make_episode(episode_id="EP-00001", task_name="pick cup", quality="good")
    make_episode(episode_id="EP-00002", task_name="pick cup", quality="bad")
    make_episode(episode_id="EP-00003", task_name="fold towel", quality="good")
    assign(operator, new_request(), "EP-00001")

    page = operator.get("/api/episodes", params={"task_name": " Pick Cup", "quality": "good"}).json()
    assert page["total"] == 1 and page["items"][0]["assigned_request_id"] is not None
    page = operator.get("/api/episodes", params={"unassigned_only": "true"}).json()
    assert {e["episode_id"] for e in page["items"]} == {"EP-00002", "EP-00003"}


def test_over_assigning_does_not_block_delivery(setup, make_episode):
    """'At least episodes_requested': extra episodes (e.g. spares) must not make a request undeliverable."""
    _, operator, new_request = setup
    for n in (1, 2, 3):
        make_episode(episode_id=f"EP-0000{n}")
    request_id = new_request(count=2)
    assign(operator, request_id, "EP-00001", "EP-00002", "EP-00003")
    response = operator.post(f"/api/requests/{request_id}/transitions", json={"to_status": "delivered"})
    assert response.status_code == 200, response.text
