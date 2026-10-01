from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.db import get_db
from app.deps import get_current_user, require_roles
from app.models import (
    ASSIGNABLE_QUALITIES,
    STAFF_ROLES,
    Assignment,
    DatasetRequest,
    Episode,
    Role,
    Status,
    StatusEvent,
    User,
)
from app.normalise import normalise_episode_id
from app.schemas import AssignIn, EpisodeOut, RequestCreate, RequestDetail, RequestOut, StatusEventOut, TransitionIn
from app.workflow import TransitionError, allowed_transitions, check_transition

router = APIRouter(prefix="/api/requests", tags=["requests"])


def publish(event: dict) -> None:
    """Replaced by the SSE broker in Task 10."""



def _load_for_user(db: Session, request_id: int, user: User, *, lock: bool = False) -> DatasetRequest:
    stmt = (
        select(DatasetRequest)
        .where(DatasetRequest.id == request_id)
        .options(
            selectinload(DatasetRequest.client),
            selectinload(DatasetRequest.events).selectinload(StatusEvent.actor),
            selectinload(DatasetRequest.assignments).selectinload(Assignment.episode),
        )
    )
    if lock:
        # Row lock until commit: two people changing the same request are serialised,
        # so e.g. "deliver" can't run while another operator is unassigning episodes.
        stmt = stmt.with_for_update()
    request = db.scalar(stmt)
    # A client asking for someone else's request gets the same 404 as a missing one.
    if request is None or (user.role == Role.CLIENT and request.client_id != user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Request not found")
    return request


def _to_out(request: DatasetRequest, assigned_count: int) -> RequestOut:
    return RequestOut(
        id=request.id, client_id=request.client_id, client_name=request.client.name,
        task_name=request.task_name, episodes_requested=request.episodes_requested,
        deadline=request.deadline, notes=request.notes, status=request.status,
        created_at=request.created_at, updated_at=request.updated_at, assigned_count=assigned_count,
    )


def _detail(db: Session, request_id: int, user: User) -> RequestDetail:
    request = _load_for_user(db, request_id, user)
    assignments = []
    for assignment in request.assignments:
        episode = EpisodeOut.model_validate(assignment.episode)
        episode.assigned_request_id = request.id
        assignments.append(episode)
    return RequestDetail(
        **_to_out(request, len(request.assignments)).model_dump(),
        history=[
            StatusEventOut(from_status=e.from_status, to_status=e.to_status, actor_id=e.actor_id,
                           actor_name=e.actor.name, note=e.note, created_at=e.created_at)
            for e in request.events
        ],
        assignments=assignments,
        allowed_transitions=allowed_transitions(Status(request.status), Role(user.role)),
    )


@router.post("", response_model=RequestDetail, status_code=status.HTTP_201_CREATED)
def create_request(body: RequestCreate, db: Session = Depends(get_db),
                   user: User = Depends(require_roles(Role.CLIENT))) -> RequestDetail:
    request = DatasetRequest(client_id=user.id, task_name=body.task_name, episodes_requested=body.episodes_requested,
                             deadline=body.deadline, notes=body.notes, status=Status.SUBMITTED)
    db.add(request)
    db.flush()  # get request.id before writing the history row
    db.add(StatusEvent(request_id=request.id, from_status=None, to_status=Status.SUBMITTED, actor_id=user.id))
    db.commit()
    publish({"type": "request.created", "data": {"id": request.id}})
    return _detail(db, request.id, user)


@router.get("", response_model=list[RequestOut])
def list_requests(status_filter: Status | None = Query(default=None, alias="status"),
                  db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[RequestOut]:
    assigned_count = (
        select(func.count()).select_from(Assignment)
        .where(Assignment.request_id == DatasetRequest.id).scalar_subquery()
    )
    stmt = (
        select(DatasetRequest, assigned_count)
        .options(selectinload(DatasetRequest.client))
        .order_by(DatasetRequest.created_at.desc(), DatasetRequest.id.desc())
    )
    if user.role == Role.CLIENT:
        stmt = stmt.where(DatasetRequest.client_id == user.id)
    if status_filter is not None:
        stmt = stmt.where(DatasetRequest.status == status_filter)
    return [_to_out(request, count) for request, count in db.execute(stmt)]


@router.get("/{request_id}", response_model=RequestDetail)
def get_request(request_id: int, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)) -> RequestDetail:
    return _detail(db, request_id, user)


@router.post("/{request_id}/transitions", response_model=RequestDetail)
def transition_request(request_id: int, body: TransitionIn, db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)) -> RequestDetail:
    request = _load_for_user(db, request_id, user, lock=True)
    current = Status(request.status)
    try:
        check_transition(current, body.to_status, Role(user.role))
    except TransitionError as exc:
        raise HTTPException(exc.http_status, str(exc)) from None
    
    assigned = len(request.assignments)
    if body.to_status == Status.DELIVERED and assigned < request.episodes_requested:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot deliver yet: only {assigned} of {request.episodes_requested} episodes are assigned.",
        )

    request.status = body.to_status
    db.add(StatusEvent(request_id=request.id, from_status=current, to_status=body.to_status,
                       actor_id=user.id, note=body.note))
    db.commit()
    publish({"type": "request.status_changed", "data": {"id": request.id, "status": body.to_status}})
    return _detail(db, request_id, user)


staff_only = require_roles(*STAFF_ROLES)


def _require_in_progress(request: DatasetRequest) -> None:
    if request.status != Status.IN_PROGRESS:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Episodes can only be changed while the request is in_progress (it is {request.status})")


@router.post("/{request_id}/assignments", response_model=RequestDetail)
def assign_episodes(request_id: int, body: AssignIn, db: Session = Depends(get_db),
                    user: User = Depends(staff_only)) -> RequestDetail:
    request = _load_for_user(db, request_id, user, lock=True)
    _require_in_progress(request)
    wanted = {normalise_episode_id(e) for e in body.episode_ids}

    episodes = {e.episode_id: e for e in db.scalars(select(Episode).where(Episode.episode_id.in_(wanted)))}
    missing = sorted(wanted - episodes.keys())
    if missing:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown episodes: {', '.join(missing)}")

    not_assignable = sorted(eid for eid, e in episodes.items() if e.quality not in ASSIGNABLE_QUALITIES)
    if not_assignable:
        raise HTTPException(422,
                            f"Only good or usable episodes can be assigned: {', '.join(not_assignable)}")

    current = db.execute(
        select(Assignment.episode_id, Assignment.request_id).where(Assignment.episode_id.in_(wanted))
    ).all()
    elsewhere = sorted(eid for eid, rid in current if rid != request.id)
    if elsewhere:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Already assigned to another request: {', '.join(elsewhere)}")

    already_here = {eid for eid, _ in current}
    for episode_id in sorted(wanted - already_here):
        db.add(Assignment(request_id=request.id, episode_id=episode_id, assigned_by_id=user.id))
    try:
        db.commit()
    except IntegrityError:
        # Another operator assigned one of these episodes between our check and our insert.
        # The UNIQUE constraint caught it; report it the same way as the normal check.
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "One of these episodes was just assigned elsewhere; refresh and try again") from None
    publish({"type": "request.assignments_changed", "data": {"id": request_id}})
    return _detail(db, request_id, user)


@router.delete("/{request_id}/assignments/{episode_id}", response_model=RequestDetail)
def unassign_episode(request_id: int, episode_id: str, db: Session = Depends(get_db),
                     user: User = Depends(staff_only)) -> RequestDetail:
    request = _load_for_user(db, request_id, user, lock=True)
    _require_in_progress(request)
    assignment = db.scalar(select(Assignment).where(
        Assignment.request_id == request_id, Assignment.episode_id == normalise_episode_id(episode_id)))
    if assignment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That episode is not assigned to this request")
    db.delete(assignment)
    db.commit()
    publish({"type": "request.assignments_changed", "data": {"id": request_id}})
    return _detail(db, request_id, user)
