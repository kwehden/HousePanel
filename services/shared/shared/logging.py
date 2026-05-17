from __future__ import annotations
import json
import logging
import sys
from datetime import datetime, timezone


class _JsonFormatter(logging.Formatter):
    def __init__(self, service_name: str) -> None:
        super().__init__()
        self._service = service_name

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "service": self._service,
            "event": getattr(record, "event", record.getMessage()),
            "message": record.getMessage(),
        }
        # Merge any extra fields passed via the `extra=` kwarg
        for key, val in record.__dict__.items():
            if key not in (
                "name", "msg", "args", "levelname", "levelno", "pathname",
                "filename", "module", "exc_info", "exc_text", "stack_info",
                "lineno", "funcName", "created", "msecs", "relativeCreated",
                "thread", "threadName", "processName", "process", "message",
                "taskName",
            ) and not key.startswith("_"):
                entry[key] = val
        if record.exc_info:
            entry["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(entry)


def make_logger(service_name: str) -> logging.Logger:
    """Return a JSON-structured stdout logger for the given service."""
    logger = logging.getLogger(service_name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(_JsonFormatter(service_name))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


def log_event(logger: logging.Logger, event: str, level: str = "info", **kwargs: object) -> None:
    """Emit a structured log line with an explicit event name and optional extra fields."""
    log_fn = getattr(logger, level, logger.info)
    log_fn(event, extra={"event": event, **kwargs})
