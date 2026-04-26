"""
Shared pytest fixtures for the AI Vendor Recommendation System test suite.

Note: VendorProfile and JobEvent are imported lazily via importlib so this
file remains syntactically valid even before the model modules are created
(Task 2 implements these).  The package path ``backend/lambda/`` cannot be
imported with a plain ``import`` statement because ``lambda`` is a Python
reserved keyword; importlib.import_module is used instead.
"""
from __future__ import annotations

import importlib
import pytest
from unittest.mock import patch, MagicMock

# ---------------------------------------------------------------------------
# Lazy model imports — wrapped in try/except so the conftest is importable
# before backend/lambda/models/ is populated (Task 2 implements these).
# ---------------------------------------------------------------------------
try:
    _vendor_mod = importlib.import_module("backend.lambda.models.vendor")
    VendorProfile = _vendor_mod.VendorProfile
except (ImportError, ModuleNotFoundError):  # pragma: no cover
    VendorProfile = None  # type: ignore[assignment,misc]

try:
    _job_mod = importlib.import_module("backend.lambda.models.job")
    JobEvent = _job_mod.JobEvent
except (ImportError, ModuleNotFoundError):  # pragma: no cover
    JobEvent = None  # type: ignore[assignment,misc]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_vendor_profile():
    """Return a valid VendorProfile instance for use in tests."""
    if VendorProfile is None:
        pytest.skip("VendorProfile model not yet implemented (Task 2)")

    return VendorProfile(
        vendorId="11111111-1111-1111-1111-111111111111",
        name="Acme Plumbing Co.",
        completionRate=0.92,
        availability="available",
        reworkRate=0.05,
        location="Austin, TX",
        specializations=["plumbing", "drainage"],
        avgResponseTime=2.5,
        slaBreachCount=1,
        activeJobs=3,
    )


@pytest.fixture
def sample_job_event():
    """Return a valid JobEvent instance for use in tests."""
    if JobEvent is None:
        pytest.skip("JobEvent model not yet implemented (Task 2)")

    return JobEvent(
        jobId="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        type="plumbing",
        location="Austin, TX",
        urgency="High",
        slaDeadline="2025-12-31T23:59:59Z",
        description="Burst pipe in commercial kitchen requiring immediate repair.",
        createdAt="2025-07-28T10:00:00Z",
        schemaVersion="1.0",
        status="Pending",
    )


@pytest.fixture
def mock_dynamodb():
    """
    Stub DynamoDB calls via unittest.mock.patch.

    Patches boto3.resource so that any code under test that calls
    boto3.resource('dynamodb') receives a MagicMock instead of making
    real AWS API calls.

    Usage in a test::

        def test_something(mock_dynamodb):
            table_mock = mock_dynamodb.Table.return_value
            table_mock.get_item.return_value = {"Item": {...}}
            ...
    """
    with patch("boto3.resource") as mock_resource:
        mock_dynamodb_resource = MagicMock()
        mock_resource.return_value = mock_dynamodb_resource
        yield mock_dynamodb_resource
