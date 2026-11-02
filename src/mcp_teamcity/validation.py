"""Validation and escaping for values that end up in URLs or locators.

Every tool argument that reaches TeamCity goes through one of these helpers.
IDs are checked against TeamCity's formats and rejected otherwise; free text
(branch names, tags, usernames, build numbers) is wrapped in TeamCity's
``$base64:`` locator syntax when it contains characters that could change the
meaning of a locator (``,``, ``:``, ``(``, ``)``, ``$``).
"""

from __future__ import annotations

import base64
import re
from urllib.parse import quote

# Project and build-configuration IDs: Latin letters, digits and underscores,
# at most 225 characters. `_Root` starts with an underscore.
_EXTERNAL_ID_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,224}")
_NUMERIC_RE = re.compile(r"\d{1,19}")
# TeamCity's REST date format: yyyyMMdd'T'HHmmssZ, e.g. 20240101T000000+0000.
_DATE_RE = re.compile(r"\d{8}T\d{6}[+-]\d{4}")
# A test occurrence ID as returned by get_build_test_results.
_TEST_OCCURRENCE_RE = re.compile(r"build:\(id:\d{1,19}\),id:-?\d{1,19}|id:-?\d{1,19},build:\(id:\d{1,19}\)")
# Characters that are safe inside a locator value without escaping.
_PLAIN_VALUE_RE = re.compile(r"[A-Za-z0-9_.\-/ *@+=]+")

BUILD_STATUSES = ("SUCCESS", "FAILURE", "ERROR", "UNKNOWN")


class InvalidArgument(ValueError):
    """A tool argument failed validation; the message is safe to show the model."""


def build_id(value: str | int) -> str:
    """A numeric build ID (the internal ID, not the build number)."""
    text = str(value).strip()
    if not _NUMERIC_RE.fullmatch(text):
        raise InvalidArgument(f"build_id must be a number (the internal build ID), got {value!r}")
    return text


def numeric_id(value: str | int, name: str) -> str:
    text = str(value).strip()
    if not _NUMERIC_RE.fullmatch(text):
        raise InvalidArgument(f"{name} must be a number, got {value!r}")
    return text


def external_id(value: str, name: str) -> str:
    """A project or build-configuration ID such as ``MyProject_Build``."""
    text = value.strip()
    if not _EXTERNAL_ID_RE.fullmatch(text):
        raise InvalidArgument(
            f"{name} must be a TeamCity ID (letters, digits and underscores, e.g. 'MyProject_Build'), got {value!r}"
        )
    return text


def date(value: str, name: str) -> str:
    text = value.strip()
    if not _DATE_RE.fullmatch(text):
        raise InvalidArgument(f"{name} must look like 20240101T000000+0000, got {value!r}")
    return text


def status(value: str) -> str:
    text = value.strip().upper()
    if text not in BUILD_STATUSES:
        raise InvalidArgument(f"status must be one of {', '.join(BUILD_STATUSES)}, got {value!r}")
    return text


def test_occurrence_id(value: str) -> str:
    text = value.strip()
    if not _TEST_OCCURRENCE_RE.fullmatch(text):
        raise InvalidArgument(
            f"test_locator must be the 'id' of a test occurrence, e.g. 'build:(id:123),id:2000000001', got {value!r}"
        )
    return text


def locator_value(value: str) -> str:
    """Escape free text for use as a locator dimension value.

    Plain values pass through unchanged so locators stay readable in logs;
    anything else is sent as ``$base64:<value>``, which TeamCity decodes after
    parsing the locator, so it cannot add or close dimensions.
    """
    if value and _PLAIN_VALUE_RE.fullmatch(value):
        return value
    return "$base64:" + base64.b64encode(value.encode()).decode().rstrip("=")


def artifact_path(value: str) -> str:
    """A relative artifact path, URL-encoded for the path of a REST call.

    Rejects ``..`` segments, backslashes and control characters so the path
    cannot leave the build's artifact tree.
    """
    clean = value.strip().strip("/")
    if "\\" in clean or any(ord(ch) < 32 for ch in clean):
        raise InvalidArgument(f"artifact path contains invalid characters: {value!r}")
    if any(segment in ("..", ".") for segment in clean.split("/")):
        raise InvalidArgument(f"artifact path must not contain '.' or '..' segments: {value!r}")
    return clean


def quote_path(clean_artifact_path: str) -> str:
    return quote(clean_artifact_path, safe="/")


def invalid(exc: InvalidArgument) -> dict[str, str]:
    """Error response for a rejected argument."""
    return {"error": "Invalid argument", "reason": str(exc)}
