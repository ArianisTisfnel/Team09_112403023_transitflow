"""
StructuredLogger — JSON structured logging for TransitFlow observability.

Every log call emits one JSON object per line to stdout, guaranteed to
include `timestamp`, `event`, and any extra keyword args (e.g. `tool`,
`duration_ms`).  Exception stack traces are serialised as a string under
`stack_trace` so nested payloads stay valid JSON.
"""
from __future__ import annotations

import json
import logging
import traceback
from datetime import datetime, timezone


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data: dict = getattr(record, "structured", None) or {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event":     record.getMessage(),
        }
        return json.dumps(data, ensure_ascii=False, default=str)


class StructuredLogger:
    """
    Thin wrapper around stdlib logging that emits one JSON line per call.

    Mandatory fields in every output record: timestamp, event.
    Callers pass any extra context as keyword args (tool, duration_ms, …).
    """

    def __init__(self, name: str, level: int = logging.DEBUG) -> None:
        self._logger = logging.getLogger(name)
        if not self._logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(_JsonFormatter())
            self._logger.addHandler(handler)
            self._logger.setLevel(level)
            self._logger.propagate = False

    def info(self, event: str, **kwargs) -> None:
        self._emit(logging.INFO, event, **kwargs)

    def warning(self, event: str, **kwargs) -> None:
        self._emit(logging.WARNING, event, **kwargs)

    def error(self, event: str, exc: BaseException | None = None, **kwargs) -> None:
        if exc is not None:
            kwargs.setdefault("stack_trace", traceback.format_exc())
        self._emit(logging.ERROR, event, **kwargs)

    def debug(self, event: str, **kwargs) -> None:
        self._emit(logging.DEBUG, event, **kwargs)

    def _emit(self, level: int, event: str, **kwargs) -> None:
        record = self._logger.makeRecord(
            self._logger.name, level, "(structured)", 0, "", (), None
        )
        record.structured = {  # type: ignore[attr-defined]
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event":     event,
            **kwargs,
        }
        self._logger.handle(record)
