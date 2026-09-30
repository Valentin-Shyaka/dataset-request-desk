import io
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.importer import CleanRow, ImportFileError, import_episodes, parse_csv, parse_duration
from app.models import Episode, Role

SEED_CSV = Path(__file__).resolve().parents[2] / "seed" / "episodes.csv"
ROBOTS = {"arm-01", "arm-02", "arm-03", "mobile-01", "humanoid-01"}
HEADER = "episode_id,robot_id,task_name,recorded_at,duration_seconds,operator_name,quality\n"


def parse(body: str):
    return parse_csv(io.StringIO(HEADER + body), ROBOTS)


def test_normalises_formatting():
    rows, report = parse("ep-00001 , ARM-01,  Pick   Cup ,14/08/2026 09:15,34,,USABLE\n")
    assert report.skipped == []
    assert rows == [CleanRow("EP-00001", "arm-01", "pick cup", datetime(2026, 8, 14, 9, 15, tzinfo=UTC),
                             34, None, "usable")]


@pytest.mark.parametrize("raw", ["2026-08-14T09:20:00", "2026-08-14 09:20:00", "2026-08-14T09:20:00Z"])
def test_accepts_known_date_formats_as_utc(raw):
    rows, _ = parse(f"EP-1,arm-01,pick cup,{raw},10,A,good\n")
    assert rows[0].recorded_at == datetime(2026, 8, 14, 9, 20, tzinfo=UTC)


def test_keeps_quoted_commas_in_task_name():
    rows, _ = parse('EP-1,arm-01,"pick cup, then place",2026-08-21T11:00:00,40,Eric,good\n')
    assert rows[0].task_name == "pick cup, then place"


@pytest.mark.parametrize("line,reason", [
    (",arm-01,pick cup,2026-08-13T06:59:00,82,P,good", "invalid episode_id"),
    ("EP-1,arm-99,pick cup,2026-08-13T06:59:00,82,P,good", "unknown robot_id"),
    ("EP-1,,pick cup,2026-08-13T06:59:00,82,P,good", "unknown robot_id"),
    ("EP-1,arm-01,,2026-08-13T06:59:00,82,P,good", "task_name is empty"),
    ("EP-1,arm-01,pick cup,not a date,82,P,good", "unrecognised recorded_at"),
    ("EP-1,arm-01,pick cup,2026-08-13T06:59:00,82,P,excellent", "invalid quality"),
    ("EP-1,arm-01,pick cup,2026-08-13T06:59:00,82,P,", "invalid quality"),
    ("EP-1,arm-02,open drawer,2026-08-20T10:00:00,30", "expected 7 columns, got 5"),
])
def test_rejects_rows_that_would_need_guessing(line, reason):
    rows, report = parse(line + "\n")
    assert rows == []
    [skipped] = report.skipped
    assert skipped.line == 2
    assert reason in skipped.reason


@pytest.mark.parametrize("raw", ["45.5", "", "-5", "0", "N/A", "999999"])
def test_parse_duration_rejects_non_whole_or_implausible(raw):
    with pytest.raises(ValueError):
        parse_duration(raw)


def test_parse_duration_accepts_whole_seconds():
    assert parse_duration(" 120 ") == 120


def test_identical_duplicates_keep_first_and_report_the_rest():
    line = "EP-1,arm-01,pick cup,2026-08-13T06:59:00,82,P,good\n"
    rows, report = parse(line + line)
    assert len(rows) == 1
    assert report.skipped[0].line == 3 and "duplicate of line 2" in report.skipped[0].reason


def test_conflicting_duplicates_reject_every_copy():
    rows, report = parse(
        "EP-1,arm-01,pick cup,2026-08-13T06:59:00,82,P,good\n"
        "ep-1,arm-01,pick cup,2026-08-13T06:59:00,82,P,bad\n"
    )
    assert rows == []
    assert [s.line for s in report.skipped] == [2, 3]
    assert all("conflicting values" in s.reason for s in report.skipped)


def test_blank_lines_are_reported():
    _, report = parse("\n   \n")
    assert [s.reason for s in report.skipped] == ["blank line", "blank line"]


def test_wrong_header_is_a_file_error():
    with pytest.raises(ImportFileError):
        parse_csv(io.StringIO("id,robot\nEP-1,arm-01\n"), ROBOTS)


def test_seed_file_import_is_idempotent(db):
    with SEED_CSV.open(encoding="utf-8-sig", newline="") as f:
        first = import_episodes(db, f)
    assert (first.rows_read, first.inserted, first.updated, len(first.skipped)) == (191, 171, 0, 20)

    with SEED_CSV.open(encoding="utf-8-sig", newline="") as f:
        second = import_episodes(db, f)
    assert (second.inserted, second.updated, second.unchanged) == (0, 0, 171)
    assert db.scalar(select(func.count()).select_from(Episode)) == 171


def test_reimport_updates_changed_rows(db):
    import_episodes(db, io.StringIO(HEADER + "EP-1,arm-01,pick cup,2026-08-13T06:59:00,82,P,good\n"))
    report = import_episodes(db, io.StringIO(HEADER + "EP-1,arm-01,pick cup,2026-08-13T06:59:00,82,P,usable\n"))
    assert (report.inserted, report.updated, report.unchanged) == (0, 1, 0)
    db.expire_all()
    assert db.get(Episode, "EP-1").quality == "usable"


def test_import_endpoint_is_staff_only(login, make_user):
    client = login(make_user(Role.CLIENT))
    response = client.post("/api/episodes/import", files={"file": ("e.csv", HEADER.encode(), "text/csv")})
    assert response.status_code == 403


def test_import_endpoint_handles_excel_bom_and_crlf(login, make_user):
    operator = login(make_user(Role.OPERATOR))
    body = ("﻿" + HEADER + "EP-1,arm-01,pick cup,2026-08-13T06:59:00,82,P,good\n").replace("\n", "\r\n")
    response = operator.post("/api/episodes/import", files={"file": ("e.csv", body.encode(), "text/csv")})
    assert response.status_code == 200, response.text
    assert response.json()["inserted"] == 1


@pytest.mark.parametrize("payload", [b"\xff\xfe\x00garbage", b"not,the,right,header\n"])
def test_import_endpoint_rejects_unreadable_files_with_400(login, make_user, payload):
    operator = login(make_user(Role.OPERATOR))
    response = operator.post("/api/episodes/import", files={"file": ("e.csv", payload, "text/csv")})
    assert response.status_code == 400


def test_cli_prints_only_the_report_on_stdout(capsys):
    """Regression: log lines used to go to stdout too, so `... | jq` broke. Logs belong on stderr."""
    import json
    import logging

    from app import cli

    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    try:
        cli.main(["import-episodes", str(SEED_CSV)])
    finally:
        root.handlers[:] = saved_handlers  # cli.main reconfigures logging; don't leak that into other tests
    report = json.loads(capsys.readouterr().out)
    assert report["inserted"] == 171
