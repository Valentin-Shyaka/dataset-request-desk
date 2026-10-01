from datetime import date, timedelta

import pytest

from app.models import Role

TOMORROW = (date.today() + timedelta(days=1)).isoformat()


def new_request(client, **overrides):
    body = {"task_name": "Pick Cup", "episodes_requested": 2, "deadline": TOMORROW, "notes": ""} | overrides
    response = client.post("/api/requests", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def move(client, request_id, to_status, note=None):
    return client.post(f"/api/requests/{request_id}/transitions", json={"to_status": to_status, "note": note})


@pytest.fixture
def actors(login, make_user):
    acme, beta = make_user(Role.CLIENT, name="Acme"), make_user(Role.CLIENT, name="Beta")
    operator = make_user(Role.OPERATOR, name="Olu")
    return {"acme": login(acme), "beta": login(beta), "op": login(operator),
            "admin": login(make_user(Role.ADMIN)), "acme_user": acme, "op_user": operator}


def test_client_creates_request_in_submitted_with_audit_entry(actors):
    created = new_request(actors["acme"])
    assert created["status"] == "submitted" and created["task_name"] == "pick cup"
    detail = actors["acme"].get(f"/api/requests/{created['id']}").json()
    assert [(h["from_status"], h["to_status"], h["actor_name"]) for h in detail["history"]] == \
        [(None, "submitted", "Acme")]


@pytest.mark.parametrize("who", ["op", "admin"])
def test_staff_cannot_create_requests(actors, who):
    response = actors[who].post("/api/requests", json={"task_name": "x", "episodes_requested": 1, "deadline": TOMORROW})
    assert response.status_code == 403


@pytest.mark.parametrize("body", [
    {"task_name": "x", "episodes_requested": 0, "deadline": TOMORROW},
    {"task_name": "   ", "episodes_requested": 1, "deadline": TOMORROW},
    {"task_name": "x", "episodes_requested": 1, "deadline": "2020-01-01"},
])
def test_invalid_request_bodies_are_422(actors, body):
    assert actors["acme"].post("/api/requests", json=body).status_code == 422


def test_clients_only_see_their_own_requests(actors):
    mine = new_request(actors["acme"])
    theirs = new_request(actors["beta"])
    assert [r["id"] for r in actors["acme"].get("/api/requests").json()] == [mine["id"]]
    # 404, not 403: don't even confirm that someone else's request exists
    assert actors["acme"].get(f"/api/requests/{theirs['id']}").status_code == 404
    assert move(actors["acme"], theirs["id"], "accepted").status_code == 404


def test_staff_see_all_requests(actors):
    new_request(actors["acme"])
    new_request(actors["beta"])
    assert len(actors["op"].get("/api/requests").json()) == 2
    assert len(actors["op"].get("/api/requests?status=submitted").json()) == 2
    assert actors["op"].get("/api/requests?status=accepted").json() == []


def test_unauthenticated_requests_are_401(anon):
    assert anon.get("/api/requests").status_code == 401
    assert anon.post("/api/requests", json={}).status_code == 401


def test_operator_starts_work_and_history_records_who(actors):
    req = new_request(actors["acme"])
    response = move(actors["op"], req["id"], "in_progress")
    assert response.status_code == 200
    assert response.json()["status"] == "in_progress"
    last = response.json()["history"][-1]
    assert (last["from_status"], last["to_status"], last["actor_name"]) == ("submitted", "in_progress", "Olu")


def test_role_and_validity_errors(actors):
    req = new_request(actors["acme"])
    assert move(actors["acme"], req["id"], "in_progress").status_code == 403  # clients can't start work
    assert move(actors["op"], req["id"], "delivered").status_code == 409     # must be in_progress first
    assert move(actors["op"], req["id"], "accepted").status_code == 409


def test_detail_lists_allowed_transitions_for_the_viewer(actors):
    req = new_request(actors["acme"])
    assert actors["op"].get(f"/api/requests/{req['id']}").json()["allowed_transitions"] == ["in_progress"]
    assert actors["acme"].get(f"/api/requests/{req['id']}").json()["allowed_transitions"] == []
