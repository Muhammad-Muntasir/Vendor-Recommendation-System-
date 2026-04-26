"""
Unit tests for backend/lambda/utils/logger.py

Requirements: 15.1
"""

from __future__ import annotations

import importlib
import json
import logging
import sys
from io import StringIO
from unittest.mock import patch

import pytest

# ``lambda`` is a Python reserved keyword — use importlib to import from
# the ``backend.lambda`` package.
_logger_mod = importlib.import_module("backend.lambda.utils.logger")
get_logger = _logger_mod.get_logger
_JsonFormatter = _logger_mod._JsonFormatter


class TestJsonFormatter:
    """Tests for the _JsonFormatter custom formatter."""

    def _make_record(self, msg: str, level: int = logging.INFO, name: str = "test.handler") -> logging.LogRecord:
        record = logging.LogRecord(
            name=name,
            level=level,
            pathname="",
            lineno=0,
            msg=msg,
            args=(),
            exc_info=None,
        )
        return record

    def test_output_is_valid_json(self):
        formatter = _JsonFormatter()
        record = self._make_record("hello world")
        output = formatter.format(record)
        parsed = json.loads(output)
        assert isinstance(parsed, dict)

    def test_required_fields_present(self):
        formatter = _JsonFormatter()
        record = self._make_record("test message")
        parsed = json.loads(formatter.format(record))
        assert "timestamp" in parsed
        assert "level" in parsed
        assert "handler" in parsed
        assert "message" in parsed

    def test_message_field_matches_input(self):
        formatter = _JsonFormatter()
        record = self._make_record("my log message")
        parsed = json.loads(formatter.format(record))
        assert parsed["message"] == "my log message"

    def test_level_field_is_level_name(self):
        formatter = _JsonFormatter()
        record = self._make_record("msg", level=logging.WARNING)
        parsed = json.loads(formatter.format(record))
        assert parsed["level"] == "WARNING"

    def test_handler_field_is_logger_name(self):
        formatter = _JsonFormatter()
        record = self._make_record("msg", name="handlers.override")
        parsed = json.loads(formatter.format(record))
        assert parsed["handler"] == "handlers.override"

    def test_timestamp_is_iso8601(self):
        formatter = _JsonFormatter()
        record = self._make_record("msg")
        parsed = json.loads(formatter.format(record))
        # ISO 8601 timestamps contain 'T' and end with '+00:00' or 'Z'
        ts = parsed["timestamp"]
        assert "T" in ts

    def test_job_id_included_when_set(self):
        formatter = _JsonFormatter()
        record = self._make_record("msg")
        record.jobId = "abc-123"
        parsed = json.loads(formatter.format(record))
        assert parsed["jobId"] == "abc-123"

    def test_job_id_absent_when_not_set(self):
        formatter = _JsonFormatter()
        record = self._make_record("msg")
        parsed = json.loads(formatter.format(record))
        assert "jobId" not in parsed

    def test_exception_info_included_when_present(self):
        formatter = _JsonFormatter()
        try:
            raise ValueError("boom")
        except ValueError:
            import sys
            exc_info = sys.exc_info()
        record = self._make_record("error occurred")
        record.exc_info = exc_info
        parsed = json.loads(formatter.format(record))
        assert "exception" in parsed
        assert "ValueError" in parsed["exception"]


class TestGetLogger:
    """Tests for the get_logger factory function."""

    def test_returns_logger_instance(self):
        logger = get_logger("test.module")
        assert isinstance(logger, logging.Logger)

    def test_logger_name_matches_argument(self):
        logger = get_logger("my.handler.name")
        assert logger.name == "my.handler.name"

    def test_logger_has_stream_handler(self):
        logger = get_logger("test.stream_handler")
        assert any(isinstance(h, logging.StreamHandler) for h in logger.handlers)

    def test_logger_handler_uses_json_formatter(self):
        logger = get_logger("test.json_formatter")
        stream_handlers = [h for h in logger.handlers if isinstance(h, logging.StreamHandler)]
        assert stream_handlers, "Expected at least one StreamHandler"
        assert isinstance(stream_handlers[0].formatter, _JsonFormatter)

    def test_same_name_returns_same_logger(self):
        logger_a = get_logger("test.same_name")
        logger_b = get_logger("test.same_name")
        assert logger_a is logger_b

    def test_no_duplicate_handlers_on_repeated_calls(self):
        name = "test.no_duplicate_handlers"
        # Reset any existing handlers for this test
        existing = logging.getLogger(name)
        existing.handlers.clear()

        get_logger(name)
        get_logger(name)
        logger = get_logger(name)
        assert len(logger.handlers) == 1

    def test_propagate_is_false(self):
        logger = get_logger("test.propagate")
        assert logger.propagate is False

    def test_logger_emits_json_to_stdout(self):
        """Verify that a log call produces valid JSON on stdout."""
        buf = StringIO()
        logger = get_logger("test.emit_json")
        # Replace the handler's stream temporarily
        for handler in logger.handlers:
            if isinstance(handler, logging.StreamHandler):
                original_stream = handler.stream
                handler.stream = buf
                break
        else:
            pytest.fail("No StreamHandler found on logger")

        try:
            logger.info("integration test message")
            output = buf.getvalue().strip()
            parsed = json.loads(output)
            assert parsed["message"] == "integration test message"
            assert parsed["level"] == "INFO"
        finally:
            handler.stream = original_stream

    def test_log_level_defaults_to_info(self):
        with patch.dict("os.environ", {}, clear=False):
            # Remove LOG_LEVEL if set
            import os
            os.environ.pop("LOG_LEVEL", None)
            logger = get_logger("test.default_level")
            assert logger.level == logging.INFO

    def test_log_level_respects_env_var(self):
        with patch.dict("os.environ", {"LOG_LEVEL": "DEBUG"}):
            # Force re-evaluation by using a fresh logger name
            logger = get_logger("test.debug_level_env")
            assert logger.level == logging.DEBUG
