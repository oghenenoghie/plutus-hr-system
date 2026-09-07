import contextvars
import json
import logging
from datetime import UTC, datetime
from typing import Any

# Set by RequestIdMiddleware (app/core/middleware.py) for the lifetime of one
# request; read here so every log line emitted while handling that request
# carries the same id without threading it through every function call.
request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)

_BASE_RECORD_ATTRS = frozenset(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line — lets Railway's log aggregation filter and
    query by request_id/level/etc. instead of grep'ing free text. Any
    caller-supplied `extra={...}` field rides along automatically (diffed
    against a bare LogRecord's own attributes), so a call site never needs
    to update this formatter to add a new field.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _BASE_RECORD_ATTRS and key not in payload:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    """Idempotent — safe to call more than once (app startup, then again
    from a test fixture) since it replaces the root logger's handlers
    rather than appending to them."""
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    handler.addFilter(_RequestIdFilter())

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers = [handler]
