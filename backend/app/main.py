import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.access_log import AccessLogMiddleware, configure_logging
from app.db import engine
from app.events import broker
from app.routers import analytics, auth, episodes, events, requests, users

configure_logging()
log = logging.getLogger("drd")



@asynccontextmanager
async def lifespan(_: FastAPI):
    broker.bind_loop(asyncio.get_running_loop())  # lets worker threads hand events to the event loop
    yield


app = FastAPI(title="Dataset Request Desk", lifespan=lifespan)
app.add_middleware(AccessLogMiddleware)
for module in (auth, users, requests, episodes, analytics, events):
    app.include_router(module.router)


@app.get("/health")
def health():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        log.exception("health check failed: database unreachable")
        return JSONResponse({"status": "degraded", "database": "unreachable"}, status_code=503)
    return {"status": "ok", "database": "ok"}
