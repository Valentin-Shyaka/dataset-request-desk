import io

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_roles
from app.importer import ImportFileError, import_episodes
from app.models import STAFF_ROLES, Assignment, Episode, Quality, User
from app.normalise import normalise_task_name
from app.schemas import EpisodeOut, EpisodePage

router = APIRouter(prefix="/api/episodes", tags=["episodes"])
staff_only = require_roles(*STAFF_ROLES)


@router.post("/import")
def import_csv(file: UploadFile, db: Session = Depends(get_db), _: User = Depends(staff_only)) -> dict:
    # utf-8-sig strips the byte-order mark that Excel adds; newline="" lets csv handle CRLF.
    text_stream = io.TextIOWrapper(file.file, encoding="utf-8-sig", newline="")
    try:
        report = import_episodes(db, text_stream)
    except (ImportFileError, UnicodeDecodeError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Cannot import this file: {exc}") from None
    return report.to_dict()


@router.get("", response_model=EpisodePage)
def list_episodes(
    task_name: str | None = None,
    quality: Quality | None = None,
    robot_id: str | None = None,
    unassigned_only: bool = False,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(staff_only),
) -> EpisodePage:
    stmt = select(Episode, Assignment.request_id).outerjoin(Assignment, Assignment.episode_id == Episode.episode_id)
    if task_name:
        stmt = stmt.where(Episode.task_name == normalise_task_name(task_name))
    if quality:
        stmt = stmt.where(Episode.quality == quality)
    if robot_id:
        stmt = stmt.where(Episode.robot_id == robot_id.strip().lower())
    if unassigned_only:
        stmt = stmt.where(Assignment.id.is_(None))

    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.execute(stmt.order_by(Episode.recorded_at.desc(), Episode.episode_id).limit(limit).offset(offset))
    items = []
    for episode, request_id in rows:
        item = EpisodeOut.model_validate(episode)
        item.assigned_request_id = request_id
        items.append(item)
    return EpisodePage(total=total, items=items)
