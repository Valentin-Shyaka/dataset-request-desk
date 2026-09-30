import json
import logging
import sys
import time
from datetime import UTC, datetime


class JsonFormatter(logging.Formatter):
    """One JSON object per line. Structured fields go in `extra={"fields": {...}}`."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        entry.update(getattr(record, "fields", {}))
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def configure_logging() -> None:
    # stderr: stdout is reserved for a command's actual output (e.g. the CLI import report)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO)
    # Route uvicorn's own logs through our JSON handler, and drop its access log (we write our own).
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).handlers.clear()
        logging.getLogger(name).propagate = True
    logging.getLogger("uvicorn.access").disabled = True


access_logger = logging.getLogger("drd.access")


class AccessLogMiddleware:
    """Plain ASGI middleware that writes one log line per HTTP request, after the response finishes.

    It is written as raw ASGI rather than @app.middleware("http") so that it also measures
    streaming responses (SSE) correctly, and so that it logs a 500 when the app crashes.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        status_code = 500  # stays 500 if the app raises before sending a response

        async def send_and_capture_status(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_and_capture_status)
        finally:
            access_logger.info("request", extra={"fields": {
                "method": scope["method"],
                "path": scope["path"],
                "status": status_code,
                "duration_ms": round((time.perf_counter() - start) * 1000, 1),
                # set by app.deps.get_current_user via request.state (which lives in scope["state"])
                "user_id": scope.get("state", {}).get("user_id"),
            }})
