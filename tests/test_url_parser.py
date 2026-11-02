"""Tests for the TeamCity URL parser."""

from __future__ import annotations

from mcp_teamcity.url_parser import parse_teamcity_url


def test_modern_build_url() -> None:
    parsed = parse_teamcity_url("https://tc.example.com/buildConfiguration/Proj_Build/12345")
    assert parsed.url_type == "build"
    assert parsed.build_type_id == "Proj_Build"
    assert parsed.build_id == "12345"


def test_modern_build_config_url() -> None:
    parsed = parse_teamcity_url("https://tc.example.com/buildConfiguration/Proj_Build")
    assert parsed.url_type == "build_config"
    assert parsed.build_type_id == "Proj_Build"
    assert parsed.build_id is None


def test_modern_project_url() -> None:
    parsed = parse_teamcity_url("https://tc.example.com/project/MyProject")
    assert parsed.url_type == "project"
    assert parsed.project_id == "MyProject"


def test_legacy_view_log_url() -> None:
    parsed = parse_teamcity_url("https://tc.example.com/viewLog.html?buildId=999&buildTypeId=Proj_Build&tab=buildLog")
    assert parsed.url_type == "build_log"
    assert parsed.build_id == "999"
    assert parsed.build_type_id == "Proj_Build"
    assert parsed.tab == "buildLog"


def test_legacy_view_type_url() -> None:
    parsed = parse_teamcity_url("https://tc.example.com/viewType.html?buildTypeId=Proj_Build")
    assert parsed.url_type == "build_config"
    assert parsed.build_type_id == "Proj_Build"


def test_build_url_takes_priority_over_config() -> None:
    # The build (with /{id}) pattern must win over the bare config pattern.
    parsed = parse_teamcity_url("https://tc.example.com/buildConfiguration/Proj_Build/42?buildTab=tests")
    assert parsed.url_type == "build"
    assert parsed.build_id == "42"
    assert parsed.tab == "tests"


def test_unknown_url() -> None:
    parsed = parse_teamcity_url("https://tc.example.com/something/else")
    assert parsed.url_type == "unknown"
    assert parsed.project_id is None
    assert parsed.build_type_id is None


def test_short_build_url_from_queue() -> None:
    parsed = parse_teamcity_url("https://tc.example.com/build/19")
    assert parsed.url_type == "build"
    assert parsed.build_id == "19"
    assert parsed.build_type_id is None


def test_change_url() -> None:
    parsed = parse_teamcity_url("https://tc.example.com/change/3?personal=false")
    assert parsed.url_type == "change"
    assert parsed.change_id == "3"


def test_legacy_project_html_url() -> None:
    parsed = parse_teamcity_url("https://tc.example.com/project.html?projectId=Payments")
    assert parsed.url_type == "project"
    assert parsed.project_id == "Payments"


def test_build_config_url_is_not_a_short_build_url() -> None:
    parsed = parse_teamcity_url("https://tc.example.com/buildConfiguration/Proj_Build/42")
    assert parsed.url_type == "build"
    assert parsed.build_type_id == "Proj_Build"
