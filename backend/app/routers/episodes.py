import io

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_roles
from app.importer import ImportFileError, import_episodes
from app.models import STAFF_ROLES, User

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
