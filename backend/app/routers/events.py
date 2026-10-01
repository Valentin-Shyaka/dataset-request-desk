import asyncio

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from app.db import SessionLocal
from app.deps import get_current_user
from app.events import broker, format_sse
from app.models import STAFF_ROLES

router = APIRouter(prefix="/api", tags=["events"])
HEARTBEAT_SECONDS = 15


def _authorize_staff(request: Request) -> None:
    # A short-lived session, closed before streaming starts: a long-lived SSE connection
    # must not hold a database connection from the pool for its whole lifetime.
    with SessionLocal() as db:
        user = get_current_user(request, db)
        if user.role not in STAFF_ROLES:
            # clients would otherwise receive events about other clients' requests
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Live updates are for staff only")


async def _stream(request: Request, queue: asyncio.Queue):
    try:
        yield ": connected\n\n"
        while not await request.is_disconnected():
            try:
                event = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
            except TimeoutError:
                yield ": heartbeat\n\n"  # keeps proxies from closing an idle connection
                continue
            yield format_sse(event)
    finally:
        broker.unsubscribe(queue)


@router.get("/events")
def stream_events(request: Request) -> StreamingResponse:
    _authorize_staff(request)
    return StreamingResponse(
        _stream(request, broker.subscribe()),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
