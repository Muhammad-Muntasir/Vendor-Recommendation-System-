"""
DynamoDB wrapper service for the AI Vendor Recommendation System.

Provides typed helpers around the boto3 DynamoDB resource so that handler
modules never interact with boto3 directly.  All write operations use
conditional expressions where appropriate to prevent silent overwrites.

Requirements: 6.5, 6.7
"""

from __future__ import annotations

import importlib
import os
from typing import Any, Optional

import boto3
from boto3.dynamodb.conditions import ConditionBase
from botocore.exceptions import BotoCoreError, ClientError

# ``lambda`` is a Python reserved keyword — use importlib for internal imports
_logger_mod = importlib.import_module("backend.lambda.utils.logger")
_logger = _logger_mod.get_logger(__name__)


# ---------------------------------------------------------------------------
# Public exception
# ---------------------------------------------------------------------------


class DynamoDBWriteError(Exception):
    """Raised when a DynamoDB write operation fails after all retries."""


# ---------------------------------------------------------------------------
# Module-level resource (reused across warm invocations)
# ---------------------------------------------------------------------------

_dynamodb_resource = None


def _get_resource():
    """Return (and lazily create) the module-level DynamoDB resource."""
    global _dynamodb_resource
    if _dynamodb_resource is None:
        _dynamodb_resource = boto3.resource("dynamodb")
    return _dynamodb_resource


def _get_table(table_name: str):
    """Return a DynamoDB Table object for *table_name*."""
    return _get_resource().Table(table_name)


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def get_item(table: str, key: dict[str, Any]) -> Optional[dict[str, Any]]:
    """
    Fetch a single item from *table* by its primary key.

    Args:
        table: DynamoDB table name.
        key:   Primary key dict, e.g. ``{"logId": "abc-123"}``.

    Returns:
        The item dict if found, or ``None`` if the key does not exist.

    Raises:
        DynamoDBWriteError: On unexpected AWS errors.
    """
    try:
        response = _get_table(table).get_item(Key=key)
        return response.get("Item")
    except (ClientError, BotoCoreError) as exc:
        _logger.error("DynamoDB get_item failed on table '%s': %s", table, exc)
        raise DynamoDBWriteError(f"get_item failed on table '{table}': {exc}") from exc


def put_item(
    table: str,
    item: dict[str, Any],
    *,
    overwrite: bool = False,
) -> None:
    """
    Write *item* to *table*.

    By default a conditional expression prevents overwriting an existing item
    that shares the same primary key.  Pass ``overwrite=True`` to skip the
    condition check (e.g. for idempotent upserts).

    Args:
        table:     DynamoDB table name.
        item:      Full item dict to write.
        overwrite: When ``False`` (default), raises :class:`DynamoDBWriteError`
                   if an item with the same key already exists.

    Raises:
        DynamoDBWriteError: If the conditional check fails or an AWS error occurs.
    """
    kwargs: dict[str, Any] = {"Item": item}

    if not overwrite:
        # Determine the partition key name from the first key in the item.
        # We use attribute_not_exists on the first key attribute to prevent
        # silent overwrites of existing records.
        first_key = next(iter(item))
        kwargs["ConditionExpression"] = f"attribute_not_exists({first_key})"

    try:
        _get_table(table).put_item(**kwargs)
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "")
        if error_code == "ConditionalCheckFailedException":
            raise DynamoDBWriteError(
                f"Item already exists in table '{table}' (conditional check failed)"
            ) from exc
        _logger.error("DynamoDB put_item failed on table '%s': %s", table, exc)
        raise DynamoDBWriteError(f"put_item failed on table '{table}': {exc}") from exc
    except BotoCoreError as exc:
        _logger.error("DynamoDB put_item failed on table '%s': %s", table, exc)
        raise DynamoDBWriteError(f"put_item failed on table '{table}': {exc}") from exc


def query(
    table: str,
    key_condition: ConditionBase,
    filter_expression: Optional[ConditionBase] = None,
    limit: Optional[int] = None,
    next_token: Optional[str] = None,
) -> dict[str, Any]:
    """
    Query *table* using a key condition expression.

    Args:
        table:             DynamoDB table name.
        key_condition:     boto3 Key condition (e.g. ``Key("jobId").eq("abc")``).
        filter_expression: Optional additional filter applied after key lookup.
        limit:             Maximum number of items to return.
        next_token:        Pagination token from a previous response.

    Returns:
        A dict with ``"Items"`` (list) and optionally ``"NextToken"`` (str).

    Raises:
        DynamoDBWriteError: On unexpected AWS errors.
    """
    kwargs: dict[str, Any] = {"KeyConditionExpression": key_condition}
    if filter_expression is not None:
        kwargs["FilterExpression"] = filter_expression
    if limit is not None:
        kwargs["Limit"] = limit
    if next_token is not None:
        kwargs["ExclusiveStartKey"] = next_token

    try:
        response = _get_table(table).query(**kwargs)
        result: dict[str, Any] = {"Items": response.get("Items", [])}
        if "LastEvaluatedKey" in response:
            result["NextToken"] = response["LastEvaluatedKey"]
        return result
    except (ClientError, BotoCoreError) as exc:
        _logger.error("DynamoDB query failed on table '%s': %s", table, exc)
        raise DynamoDBWriteError(f"query failed on table '{table}': {exc}") from exc


def scan(
    table: str,
    filter_expression: Optional[ConditionBase] = None,
) -> list[dict[str, Any]]:
    """
    Scan all items in *table*, optionally filtered.

    For large tables this performs paginated scans and returns all results.

    Args:
        table:             DynamoDB table name.
        filter_expression: Optional filter applied to each scanned item.

    Returns:
        A list of item dicts.

    Raises:
        DynamoDBWriteError: On unexpected AWS errors.
    """
    kwargs: dict[str, Any] = {}
    if filter_expression is not None:
        kwargs["FilterExpression"] = filter_expression

    items: list[dict[str, Any]] = []
    try:
        tbl = _get_table(table)
        while True:
            response = tbl.scan(**kwargs)
            items.extend(response.get("Items", []))
            last_key = response.get("LastEvaluatedKey")
            if not last_key:
                break
            kwargs["ExclusiveStartKey"] = last_key
        return items
    except (ClientError, BotoCoreError) as exc:
        _logger.error("DynamoDB scan failed on table '%s': %s", table, exc)
        raise DynamoDBWriteError(f"scan failed on table '{table}': {exc}") from exc


def update_item(
    table: str,
    key: dict[str, Any],
    update_expression: str,
    expression_attribute_values: Optional[dict[str, Any]] = None,
    expression_attribute_names: Optional[dict[str, str]] = None,
) -> Optional[dict[str, Any]]:
    """
    Update an existing item in *table*.

    Args:
        table:                      DynamoDB table name.
        key:                        Primary key dict identifying the item.
        update_expression:          DynamoDB UpdateExpression string.
        expression_attribute_values: Mapping of placeholder → value.
        expression_attribute_names:  Mapping of placeholder → attribute name.

    Returns:
        The updated item attributes dict (``ALL_NEW``), or ``None`` on failure.

    Raises:
        DynamoDBWriteError: On unexpected AWS errors.
    """
    kwargs: dict[str, Any] = {
        "Key": key,
        "UpdateExpression": update_expression,
        "ReturnValues": "ALL_NEW",
    }
    if expression_attribute_values:
        kwargs["ExpressionAttributeValues"] = expression_attribute_values
    if expression_attribute_names:
        kwargs["ExpressionAttributeNames"] = expression_attribute_names

    try:
        response = _get_table(table).update_item(**kwargs)
        return response.get("Attributes")
    except (ClientError, BotoCoreError) as exc:
        _logger.error("DynamoDB update_item failed on table '%s': %s", table, exc)
        raise DynamoDBWriteError(f"update_item failed on table '{table}': {exc}") from exc
