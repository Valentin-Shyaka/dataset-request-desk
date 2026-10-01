"""The request status machine. The whole policy is the TRANSITIONS table:
if a (from, to) pair is not listed, the move is impossible."""
from app.models import STAFF_ROLES, Role, Status

STAFF = frozenset(STAFF_ROLES)
CLIENT = frozenset({Role.CLIENT})

# (from_status, to_status) -> the roles allowed to make that move.
TRANSITIONS: dict[tuple[Status, Status], frozenset[Role]] = {
    (Status.SUBMITTED, Status.IN_PROGRESS): STAFF,
    (Status.IN_PROGRESS, Status.DELIVERED): STAFF,
    (Status.DELIVERED, Status.ACCEPTED): CLIENT,
    (Status.DELIVERED, Status.REJECTED): CLIENT,
    (Status.REJECTED, Status.IN_PROGRESS): STAFF,  # rework
}


class TransitionError(Exception):
    def __init__(self, message: str, http_status: int):
        super().__init__(message)
        self.http_status = http_status


def check_transition(current: Status, target: Status, role: Role) -> None:
    """Return None if `role` may move a request from `current` to `target`.
    Otherwise raise TransitionError:
      - 409 if the move doesn't exist at all (not in TRANSITIONS)
      - 403 if the move exists but this role isn't allowed to make it
    """
    if (current, target) not in TRANSITIONS:
        raise TransitionError(f"A request cannot move from {current} to {target}", 409)
    if role not in TRANSITIONS[(current, target)]:
        raise TransitionError(f"The {role} role cannot move a request from {current} to {target}", 403)


def allowed_transitions(current: Status, role: Role) -> list[Status]:
    """The statuses `role` could move a request to from `current` (the UI shows these as buttons)."""
    return [target for target in Status if (current, target) in TRANSITIONS and role in TRANSITIONS[(current, target)]]
