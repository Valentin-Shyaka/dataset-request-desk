"""CSV import of episodes from the recording system.

Policy: normalise *formatting* (whitespace, casing, known date formats) but never guess
*values*. Any row that would need a guess is skipped and reported with its line number.
"""
import csv
import logging
import re
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from typing import TextIO

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import Assignment, Episode, Quality, Robot
from app.normalise import normalise_episode_id, normalise_task_name

EXPECTED_HEADER = ["episode_id", "robot_id", "task_name", "recorded_at",
                   "duration_seconds", "operator_name", "quality"]
DATA_COLUMNS = EXPECTED_HEADER[1:]  # everything except the key
# [0-9] not \d (which also matches e.g. Arabic-Indic digits); length fits the 50-char column.
EPISODE_ID_RE = re.compile(r"EP-[0-9]{1,47}")
MAX_TEXT_LENGTH = 200  # task_name and operator_name columns are VARCHAR(200)
MAX_DURATION_SECONDS = 4 * 60 * 60
BATCH_SIZE = 1000
VALID_QUALITIES = {q.value for q in Quality}

log = logging.getLogger("drd.import")


class ImportFileError(ValueError):
    """The file as a whole is unusable (e.g. wrong header)."""


class RowError(ValueError):
    """One row is unusable; the message becomes the skip reason."""


@dataclass(frozen=True)
class CleanRow:
    episode_id: str
    robot_id: str
    task_name: str
    recorded_at: datetime
    duration_seconds: int
    operator_name: str | None
    quality: str
    line: int = field(default=0, compare=False)  # where it came from; not part of the episode's data

    def values(self) -> dict:
        return {"episode_id": self.episode_id} | {column: getattr(self, column) for column in DATA_COLUMNS}


@dataclass
class Skipped:
    line: int
    episode_id: str | None
    reason: str


@dataclass
class ImportReport:
    rows_read: int = 0
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped: list[Skipped] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self) | {"skipped_count": len(self.skipped)}


def parse_timestamp(raw: str) -> datetime:
    value = raw.strip()
    try:
        parsed = datetime.fromisoformat(value)  # handles 'T' or ' ' separators and a trailing 'Z'
    except ValueError:
        try:
            parsed = datetime.strptime(value, "%d/%m/%Y %H:%M")  # day-first, as in the export
        except ValueError:
            raise RowError(f"unrecognised recorded_at {raw!r}") from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)  # the recording system exports UTC
    try:
        return parsed.astimezone(UTC)
    except OverflowError:  # e.g. 0001-01-01 with a positive offset falls before year 1 in UTC
        raise RowError(f"unrecognised recorded_at {raw!r}") from None


def parse_duration(raw: str) -> int:
    value = raw.strip()
    # Check the format before int(): int() would accept "-5" and "+7", and crashes on "45.5".
    if not re.fullmatch(r"[0-9]+", value):
        raise RowError(f"duration_seconds must be a whole number of seconds, got {raw!r}")
    seconds = int(value)
    if not 0 < seconds <= MAX_DURATION_SECONDS:
        raise RowError(f"duration_seconds {seconds} is outside 1..{MAX_DURATION_SECONDS}")
    return seconds


def clean_row(raw: list[str], known_robots: set[str]) -> CleanRow:
    if len(raw) != len(EXPECTED_HEADER):
        raise RowError(f"expected {len(EXPECTED_HEADER)} columns, got {len(raw)}")
    if any("\x00" in cell for cell in raw):
        raise RowError("contains a NUL character")
    episode_id, robot_id, task_name, recorded_at, duration, operator_name, quality = raw

    episode_id = normalise_episode_id(episode_id)
    if not EPISODE_ID_RE.fullmatch(episode_id):
        raise RowError(f"invalid episode_id {raw[0]!r}")
    robot_id = robot_id.strip().lower()
    if robot_id not in known_robots:
        raise RowError(f"unknown robot_id {raw[1]!r}")
    task_name = normalise_task_name(task_name)
    if not task_name:
        raise RowError("task_name is empty")
    if len(task_name) > MAX_TEXT_LENGTH:
        raise RowError(f"task_name is longer than {MAX_TEXT_LENGTH} characters")
    operator_name = operator_name.strip() or None
    if operator_name and len(operator_name) > MAX_TEXT_LENGTH:
        raise RowError(f"operator_name is longer than {MAX_TEXT_LENGTH} characters")
    quality = quality.strip().lower()
    if quality not in VALID_QUALITIES:
        raise RowError(f"invalid quality {raw[6]!r}")

    return CleanRow(
        episode_id=episode_id,
        robot_id=robot_id,
        task_name=task_name,
        recorded_at=parse_timestamp(recorded_at),
        duration_seconds=parse_duration(duration),
        operator_name=operator_name,
        quality=quality,
    )


def parse_csv(stream: TextIO, known_robots: set[str]) -> tuple[list[CleanRow], ImportReport]:
    """Pure function: text in, clean rows + report out. No database access."""
    report = ImportReport()
    reader = csv.reader(stream)
    header = [column.strip().lower() for column in next(reader, [])]
    if header != EXPECTED_HEADER:
        raise ImportFileError(f"unexpected header {header}; expected {EXPECTED_HEADER}")

    first_seen: dict[str, tuple[int, CleanRow]] = {}
    conflicts: dict[str, list[int]] = {}

    try:
        rows_with_lines = [(reader.line_num, raw) for raw in reader]  # line_num: physical line in the file
    except csv.Error as exc:  # e.g. an unterminated quote swallowing the rest of the file
        raise ImportFileError(f"malformed CSV near line {reader.line_num}: {exc}") from None

    for line, raw in rows_with_lines:
        report.rows_read += 1
        if not any(cell.strip() for cell in raw):
            report.skipped.append(Skipped(line, None, "blank line"))
            continue
        try:
            row = replace(clean_row(raw, known_robots), line=line)
        except RowError as exc:
            report.skipped.append(Skipped(line, raw[0].strip() or None, str(exc)))
            continue

        seen = first_seen.get(row.episode_id)
        if seen is None:
            first_seen[row.episode_id] = (line, row)
        elif row.episode_id in conflicts:
            conflicts[row.episode_id].append(line)
        elif seen[1] == row:
            report.skipped.append(Skipped(line, row.episode_id, f"duplicate of line {seen[0]}"))
        else:
            conflicts[row.episode_id] = [seen[0], line]

    # We cannot tell which of two contradicting rows is correct, so we import neither.
    for episode_id, lines in conflicts.items():
        del first_seen[episode_id]
        reason = f"conflicting values for {episode_id} on lines {', '.join(map(str, lines))}"
        report.skipped.extend(Skipped(line, episode_id, reason) for line in lines)

    report.skipped.sort(key=lambda s: s.line)
    return [row for _, row in first_seen.values()], report


def import_episodes(db: Session, stream: TextIO) -> ImportReport:
    known_robots = set(db.scalars(select(Robot.id)))
    rows, report = parse_csv(stream, known_robots)
    for start in range(0, len(rows), BATCH_SIZE):
        _upsert_batch(db, rows[start:start + BATCH_SIZE], report)
    db.commit()  # all or nothing
    report.skipped.sort(key=lambda s: s.line)
    log.info("episode import finished", extra={"fields": {
        k: v for k, v in report.to_dict().items() if k != "skipped"
    }})
    return report


def _upsert_batch(db: Session, batch: list[CleanRow], report: ImportReport) -> None:
    episodes = Episode.__table__
    batch = _drop_changes_to_assigned_episodes(db, batch, report)  # before counting: skipped rows count once
    if not batch:
        return
    ids = [row.episode_id for row in batch]
    existing = set(db.scalars(select(episodes.c.episode_id).where(episodes.c.episode_id.in_(ids))))

    stmt = insert(episodes).values([row.values() for row in batch])
    stmt = stmt.on_conflict_do_update(
        index_elements=[episodes.c.episode_id],
        set_={column: stmt.excluded[column] for column in DATA_COLUMNS},
        # Only rewrite rows whose data really changed: re-importing the same file writes nothing.
        where=or_(*(episodes.c[column].is_distinct_from(stmt.excluded[column]) for column in DATA_COLUMNS)),
    ).returning(episodes.c.episode_id)
    written = set(db.scalars(stmt))  # rows that were inserted or updated

    report.inserted += len(written - existing)
    report.updated += len(written & existing)
    report.unchanged += len(existing - written)


def _drop_changes_to_assigned_episodes(db: Session, batch: list[CleanRow], report: ImportReport) -> list[CleanRow]:
    """An episode already assigned to a request is never changed by an import: a corrected export could
    otherwise turn it 'bad' (or move it to another task) behind the request's back. Identical data passes
    through and is counted as unchanged; a real change is skipped and reported so someone can decide."""
    ids = [row.episode_id for row in batch]
    assigned_to = dict(db.execute(
        select(Assignment.episode_id, Assignment.request_id).where(Assignment.episode_id.in_(ids))
    ).all())
    if not assigned_to:
        return batch
    current = {e.episode_id: e for e in db.scalars(select(Episode).where(Episode.episode_id.in_(assigned_to)))}
    kept = []
    for row in batch:
        stored = current.get(row.episode_id)
        if stored is not None and any(getattr(stored, c) != getattr(row, c) for c in DATA_COLUMNS):
            request_id = assigned_to[row.episode_id]
            report.skipped.append(Skipped(row.line, row.episode_id,
                                          f"assigned to request {request_id}; unassign it before changing its data"))
        else:
            kept.append(row)
    return kept
