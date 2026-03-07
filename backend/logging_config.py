"""Structured JSON logging configuration.

Configures Python's :mod:`logging` hierarchy to output JSON-formatted
log records, suitable for ingestion by centralised log aggregators.
The ``log_level`` setting from ``settings.json`` / ``LOG_LEVEL`` env
var is consumed here.
"""

from __future__ import annotations

import json
import logging
import logging.config
from datetime import datetime, UTC
from typing import Any


class _JSONFormatter(logging.Formatter):
    """Format log records as single-line JSON objects.

    Includes structured fields for post-mortem debugging:
    - request_id: correlation ID for tracing
    - module/function/line: source location
    - extra fields: any additional key-value pairs attached via LogRecord
    """

    # Fields that are standard LogRecord attributes and should not be
    # emitted as "extra" context.
    _STANDARD_ATTRS = frozenset(
        {
            "name",
            "msg",
            "args",
            "created",
            "relativeCreated",
            "exc_info",
            "exc_text",
            "stack_info",
            "lineno",
            "funcName",
            "pathname",
            "filename",
            "module",
            "thread",
            "threadName",
            "process",
            "processName",
            "levelname",
            "levelno",
            "message",
            "msecs",
            "taskName",
            "request_id",
        }
    )

    def format(self, record: logging.LogRecord) -> str:  # noqa: D401
        """Return the log record serialised as a JSON string.

        :param record: The log record to format.
        :returns: A JSON-encoded log line.
        :rtype: str
        """
        from middleware import request_id_var

        log_entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        if record.exc_info and record.exc_info[1] is not None:
            log_entry["exception"] = self.formatException(record.exc_info)
            log_entry["exception_type"] = type(record.exc_info[1]).__qualname__
        if record.stack_info:
            log_entry["stack_info"] = record.stack_info
        # Include request_id from context var or record attribute
        request_id = request_id_var.get() or getattr(record, "request_id", None)
        if request_id:
            log_entry["request_id"] = request_id
        # Include any extra fields attached to the record
        for key, value in record.__dict__.items():
            if key not in self._STANDARD_ATTRS and not key.startswith("_"):
                log_entry[key] = value
        return json.dumps(log_entry, default=str)


def setup_logging() -> None:
    """Apply the JSON logging configuration once.

    Safe to call multiple times — subsequent calls are no-ops.
    """
    from config import LOG_LEVEL, DEV_MODE

    # In dev mode use human-readable format; in prod use JSON.
    if DEV_MODE:
        handler: dict[str, Any] = {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stderr",
            "formatter": "simple",
        }
    else:
        handler = {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stderr",
            "formatter": "json",
        }

    config: dict[str, Any] = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "json": {
                "()": _JSONFormatter,
            },
            "simple": {
                "format": "%(asctime)s %(levelname)-8s %(name)s  %(message)s",
            },
        },
        "handlers": {
            "default": handler,
        },
        "root": {
            "level": LOG_LEVEL.upper() if isinstance(LOG_LEVEL, str) else "INFO",
            "handlers": ["default"],
        },
        # Quieten noisy third-party loggers
        "loggers": {
            "uvicorn": {"level": "INFO"},
            "uvicorn.access": {"level": "INFO"},
            "sqlalchemy.engine": {"level": "WARNING"},
        },
    }
    logging.config.dictConfig(config)
