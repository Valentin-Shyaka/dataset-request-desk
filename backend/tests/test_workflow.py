import itertools

import pytest

from app.models import Role, Status
from app.workflow import TransitionError, allowed_transitions, check_transition

# Straight from the brief's diagram: clients accept/reject, operators (and admins) do the rest.
ALLOWED = {
    ("submitted", "in_progress", "operator"), ("submitted", "in_progress", "admin"),
    ("in_progress", "delivered", "operator"), ("in_progress", "delivered", "admin"),
    ("delivered", "accepted", "client"),
    ("delivered", "rejected", "client"),
    ("rejected", "in_progress", "operator"), ("rejected", "in_progress", "admin"),
}


@pytest.mark.parametrize("current,target,role", list(itertools.product(Status, Status, Role)))
def test_every_combination_of_status_and_role(current, target, role):
    if (current, target, role) in ALLOWED:
        check_transition(current, target, role)  # must not raise
    else:
        with pytest.raises(TransitionError):
            check_transition(current, target, role)


def test_moves_that_exist_but_belong_to_another_role_are_403():
    with pytest.raises(TransitionError) as exc:
        check_transition(Status.DELIVERED, Status.ACCEPTED, Role.OPERATOR)
    assert exc.value.http_status == 403


def test_moves_that_do_not_exist_are_409():
    with pytest.raises(TransitionError) as exc:
        check_transition(Status.SUBMITTED, Status.DELIVERED, Role.OPERATOR)
    assert exc.value.http_status == 409


def test_allowed_transitions_for_ui():
    assert allowed_transitions(Status.DELIVERED, Role.CLIENT) == [Status.ACCEPTED, Status.REJECTED]
    assert allowed_transitions(Status.DELIVERED, Role.OPERATOR) == []
    assert allowed_transitions(Status.ACCEPTED, Role.ADMIN) == []
