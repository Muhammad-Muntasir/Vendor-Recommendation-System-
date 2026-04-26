"""
Unit tests for backend/lambda/utils/model_version.py

Requirements: 14.1, 14.3, 14.4
"""

from __future__ import annotations

import importlib
from unittest.mock import MagicMock, patch

import pytest

# ``lambda`` is a Python reserved keyword — use importlib to import from
# the ``backend.lambda`` package.
mv = importlib.import_module("backend.lambda.utils.model_version")


@pytest.fixture(autouse=True)
def reset_cache():
    """Reset the module-level cache before every test."""
    mv._reset_cache()
    yield
    mv._reset_cache()


class TestGetModelVersion:
    """Tests for the get_model_version() function."""

    def _make_s3_response(self, version: str) -> dict:
        body_mock = MagicMock()
        body_mock.read.return_value = version.encode("utf-8")
        return {"Body": body_mock}

    # ------------------------------------------------------------------
    # Happy path
    # ------------------------------------------------------------------

    def test_returns_version_from_s3(self):
        with patch.dict("os.environ", {"LAMBDA_ZIP_BUCKET": "my-bucket"}):
            with patch("boto3.client") as mock_client:
                mock_s3 = MagicMock()
                mock_client.return_value = mock_s3
                mock_s3.get_object.return_value = self._make_s3_response("1.2.3")

                result = mv.get_model_version()

        assert result == "1.2.3"

    def test_version_with_leading_trailing_whitespace_is_stripped(self):
        with patch.dict("os.environ", {"LAMBDA_ZIP_BUCKET": "my-bucket"}):
            with patch("boto3.client") as mock_client:
                mock_s3 = MagicMock()
                mock_client.return_value = mock_s3
                mock_s3.get_object.return_value = self._make_s3_response("  2.0.1\n")

                result = mv.get_model_version()

        assert result == "2.0.1"

    # ------------------------------------------------------------------
    # Caching behaviour
    # ------------------------------------------------------------------

    def test_second_call_returns_cached_value_without_s3(self):
        with patch.dict("os.environ", {"LAMBDA_ZIP_BUCKET": "my-bucket"}):
            with patch("boto3.client") as mock_client:
                mock_s3 = MagicMock()
                mock_client.return_value = mock_s3
                mock_s3.get_object.return_value = self._make_s3_response("3.0.0")

                first = mv.get_model_version()
                second = mv.get_model_version()

        assert first == second == "3.0.0"
        # S3 should only have been called once
        assert mock_s3.get_object.call_count == 1

    def test_reset_cache_clears_cached_value(self):
        with patch.dict("os.environ", {"LAMBDA_ZIP_BUCKET": "my-bucket"}):
            with patch("boto3.client") as mock_client:
                mock_s3 = MagicMock()
                mock_client.return_value = mock_s3
                mock_s3.get_object.return_value = self._make_s3_response("1.0.0")
                mv.get_model_version()

        mv._reset_cache()
        assert mv._cached_version is None

    # ------------------------------------------------------------------
    # Fallback: S3 read failure
    # ------------------------------------------------------------------

    def test_fallback_when_s3_client_error(self):
        from botocore.exceptions import ClientError
        with patch.dict("os.environ", {"LAMBDA_ZIP_BUCKET": "my-bucket"}):
            with patch("boto3.client") as mock_client:
                mock_s3 = MagicMock()
                mock_client.return_value = mock_s3
                mock_s3.get_object.side_effect = ClientError(
                    {"Error": {"Code": "NoSuchKey", "Message": "Not found"}},
                    "GetObject",
                )

                result = mv.get_model_version()

        assert result == "0.0.0"

    def test_fallback_when_generic_exception(self):
        with patch.dict("os.environ", {"LAMBDA_ZIP_BUCKET": "my-bucket"}):
            with patch("boto3.client") as mock_client:
                mock_s3 = MagicMock()
                mock_client.return_value = mock_s3
                mock_s3.get_object.side_effect = RuntimeError("network error")

                result = mv.get_model_version()

        assert result == "0.0.0"

    def test_fallback_when_bucket_env_var_missing(self):
        import os
        env = {k: v for k, v in os.environ.items() if k != "LAMBDA_ZIP_BUCKET"}
        with patch.dict("os.environ", env, clear=True):
            result = mv.get_model_version()

        assert result == "0.0.0"

    def test_fallback_when_bucket_env_var_empty_string(self):
        with patch.dict("os.environ", {"LAMBDA_ZIP_BUCKET": ""}):
            result = mv.get_model_version()

        assert result == "0.0.0"

    # ------------------------------------------------------------------
    # Fallback: invalid semver format
    # ------------------------------------------------------------------

    @pytest.mark.parametrize("bad_version", [
        "1.2",          # missing PATCH
        "1",            # only MAJOR
        "v1.2.3",       # leading 'v'
        "1.2.3.4",      # four parts
        "1.2.x",        # non-numeric PATCH
        "latest",       # arbitrary string
        "",             # empty string
        "1.2.3-beta",   # pre-release suffix
    ])
    def test_fallback_on_invalid_semver(self, bad_version):
        with patch.dict("os.environ", {"LAMBDA_ZIP_BUCKET": "my-bucket"}):
            with patch("boto3.client") as mock_client:
                mock_s3 = MagicMock()
                mock_client.return_value = mock_s3
                mock_s3.get_object.return_value = self._make_s3_response(bad_version)

                result = mv.get_model_version()

        assert result == "0.0.0"

    @pytest.mark.parametrize("good_version", [
        "0.0.0",
        "1.0.0",
        "10.20.30",
        "0.1.0",
        "999.999.999",
    ])
    def test_valid_semver_formats_accepted(self, good_version):
        with patch.dict("os.environ", {"LAMBDA_ZIP_BUCKET": "my-bucket"}):
            with patch("boto3.client") as mock_client:
                mock_s3 = MagicMock()
                mock_client.return_value = mock_s3
                mock_s3.get_object.return_value = self._make_s3_response(good_version)

                result = mv.get_model_version()

        assert result == good_version

    # ------------------------------------------------------------------
    # S3 call parameters
    # ------------------------------------------------------------------

    def test_s3_called_with_correct_bucket_and_key(self):
        with patch.dict("os.environ", {"LAMBDA_ZIP_BUCKET": "prod-lambda-zip"}):
            with patch("boto3.client") as mock_client:
                mock_s3 = MagicMock()
                mock_client.return_value = mock_s3
                mock_s3.get_object.return_value = self._make_s3_response("1.0.0")

                mv.get_model_version()

        mock_s3.get_object.assert_called_once_with(
            Bucket="prod-lambda-zip", Key="model-version.txt"
        )
