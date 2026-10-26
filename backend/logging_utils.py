from __future__ import annotations

import json
import logging
import re
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

_TRACE_ID: ContextVar[str] = ContextVar("trace_id", default="-")
_VALID_TRACE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def new_trace_id() -> str:
    return uuid.uuid4().hex[:12]


def get_trace_id() -> str:
    return _TRACE_ID.get()


def set_trace_id(value: str | None = None) -> str:
    trace_id = value if value and _VALID_TRACE.match(value) else new_trace_id()
    _TRACE_ID.set(trace_id)
    return trace_id


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "message": record.getMessage(),
            "trace_id": get_trace_id(),
            "logger": record.name,
        }
        for key, value in getattr(record, "event_fields", {}).items():
            if key not in payload:
                payload[key] = value
        if record.exc_info:
            payload["error"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(getattr(logging, str(level).upper(), logging.INFO))


def log_event(logger: logging.Logger, event: str, **fields: Any) -> None:
    record = logger.makeRecord(
        logger.name,
        logging.INFO,
        __file__,
        0,
        event,
        (),
        None,
    )
    record.event_fields = fields
    logger.handle(record)


class TraceIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        trace_id = set_trace_id(request.headers.get("X-Trace-Id"))
        response = await call_next(request)
        response.headers["X-Trace-Id"] = trace_id
        return response
