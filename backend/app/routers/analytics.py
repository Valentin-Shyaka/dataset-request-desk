"""All aggregation happens in Postgres; Python only shapes the result."""
from datetime import UTC, date, datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_roles
from app.models import STAFF_ROLES, Status, User
from app.schemas import AnalyticsOut, DayRobotCount, TaskCount

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

EPISODES_PER_DAY = text("""
SELECT (recorded_at AT TIME ZONE 'UTC')::date AS day, robot_id, count(*) AS episodes
FROM episodes
WHERE recorded_at >= :start AND recorded_at < :end
GROUP BY day, robot_id
ORDER BY day, robot_id
""")

REQUESTS_BY_STATUS = text("""
SELECT status, count(*) FROM dataset_requests
WHERE created_at >= :start AND created_at < :end
GROUP BY status

""")

MEDIAN_SECONDS_TO_FIRST_DELIVERY = text("""
WITH first_delivery AS (
SELECT request_id, MIN(created_at) AS delivered_at
FROM request_status_events
WHERE to_status = 'delivered'
GROUP BY request_id
)
SELECT EXTRACT(EPOCH FROM percentile_cont(0.5) WITHIN GROUP (ORDER BY fd.delivered_at - r.created_at))
FROM dataset_requests r
JOIN first_delivery fd ON fd.request_id = r.id
WHERE r.created_at >= :start AND r.created_at < :end

""")

TOP_TASKS_BY_GOOD = text("""
    SELECT task_name, count(*) AS good_episodes
    FROM episodes
    WHERE quality = 'good' AND recorded_at >= :start AND recorded_at < :end
    GROUP BY task_name
    ORDER BY good_episodes DESC, task_name
    LIMIT 5
""")


@router.get("", response_model=AnalyticsOut)
def analytics(
    date_from: date = Query(alias="from"),
    date_to: date = Query(alias="to"),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(*STAFF_ROLES)),
) -> AnalyticsOut:
    if date_to < date_from:
        raise HTTPException(422, "'to' must be on or after 'from'")
    # Half-open interval [start, end): 'to' is inclusive, so end is midnight after it.
    params = {
        "start": datetime.combine(date_from, time.min, tzinfo=UTC),
        "end": datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=UTC),
    }
    median = db.scalar(MEDIAN_SECONDS_TO_FIRST_DELIVERY, params)
    return AnalyticsOut(
        date_from=date_from,
        date_to=date_to,
        episodes_per_day=[DayRobotCount(**row) for row in db.execute(EPISODES_PER_DAY, params).mappings()],
        requests_by_status={s.value: 0 for s in Status} | dict(db.execute(REQUESTS_BY_STATUS, params).all()),
        median_seconds_submitted_to_delivered=float(median) if median is not None else None,
        top_tasks_by_good_episodes=[TaskCount(**row) for row in db.execute(TOP_TASKS_BY_GOOD, params).mappings()],
    )
