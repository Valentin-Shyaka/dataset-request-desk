import logging

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.access_log import AccessLogMiddleware, configure_logging
from app.db import engine
from app.routers import auth, users

configure_logging()
log = logging.getLogger("drd")

app = FastAPI(title="Dataset Request Desk")
app.add_middleware(AccessLogMiddleware)
app.include_router(auth.router)
app.include_router(users.router)


@app.get("/health")
def health():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        log.exception("health check failed: database unreachable")
        return JSONResponse({"status": "degraded", "database": "unreachable"}, status_code=503)
    return {"status": "ok", "database": "ok"}
