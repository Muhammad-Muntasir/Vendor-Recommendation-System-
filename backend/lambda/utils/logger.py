"""
Structured JSON logger for the AI Vendor Recommendation System.

Emits log records as JSON objects with the following fields:
  - timestamp  : ISO 8601 UTC timestamp
  - level      : log level name (e.g. "INFO", "WARNING", "ERROR")
  - handler    : logger name (typically the module/handler that called get_logger)
  - jobId      : optional job identifier, included when present in the log record
  - message    : the formatted log message

Requirements: 15.1
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Optional


class _JsonFormatter(logging.Formatter):
    """Custom formatter that serialises each log record as a single JSON line."""

    def format(self, record: logging.LogRecord) -> str:
        # Build the base payload
        payload: dict = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "handler": record.name,
            "message": record.getMessage(),
        }

        # Include jobId when it has been injected into the record (optional field)
        job_id: Optional[str] = getattr(record, "jobId", None)
        if job_id is not None:
            payload["jobId"] = job_id

        # Attach exception info when present
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


def get_logger(name: str) -> logging.Logger:
    """
    Return a :class:`logging.Logger` configured to emit structured JSON.

    The logger writes to *stdout* so that CloudWatch Logs can capture the
    output from the Lambda execution environment.  Calling this function
    multiple times with the same *name* returns the same logger instance
    (standard Python logging behaviour).

    Args:
        name: Logger name — typically ``__name__`` of the calling module.

    Returns:
        A :class:`logging.Logger` instance with a JSON stream handler attached.
    """
    logger = logging.getLogger(name)

    # Avoid adding duplicate handlers if get_logger is called more than once
    # for the same name (e.g. during Lambda warm invocations).
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(_JsonFormatter())
        logger.addHandler(handler)

    # Respect the LOG_LEVEL environment variable if set; default to INFO.
    import os
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    logger.setLevel(getattr(logging, level_name, logging.INFO))

    # Prevent log records from propagating to the root logger to avoid
    # duplicate output in environments that configure the root logger.
    logger.propagate = False

    return logger
