"""Tests for wsp.update_check — best-effort daily release check."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from wsp import update_check


@pytest.fixture
def isolated_state(tmp_path, monkeypatch):
    """Each test gets its own ~/.wsp/last_update_check.json."""
    monkeypatch.setenv("WSP_CACHE_DIR", str(tmp_path))
    monkeypatch.delenv("WSP_NO_UPDATE_CHECK", raising=False)
    yield tmp_path


def test_disabled_via_env(isolated_state, monkeypatch):
    monkeypatch.setenv("WSP_NO_UPDATE_CHECK", "1")
    msg = update_check.maybe_check_for_updates("1.0.0", repo="x/y")
    assert msg is None


def test_no_state_yet_fetches_and_returns_warning_when_outdated(isolated_state):
    with patch("wsp.update_check._fetch_latest_via_gh", return_value="v1.4.0"):
        msg = update_check.maybe_check_for_updates("1.0.0", repo="x/y")
    assert msg is not None
    assert "1.4.0" in msg
    assert "1.0.0" in msg


def test_no_state_yet_returns_none_when_current(isolated_state):
    with patch("wsp.update_check._fetch_latest_via_gh", return_value="v1.4.0"):
        msg = update_check.maybe_check_for_updates("1.4.0", repo="x/y")
    assert msg is None


def test_cache_skips_fetch_within_24h(isolated_state):
    state_file = isolated_state / "last_update_check.json"
    state_file.write_text(json.dumps({
        "checked_at": int(time.time()) - 60,  # 1 minute ago
        "latest": "1.4.0",
    }))
    with patch("wsp.update_check._fetch_latest_via_gh") as mock_fetch:
        msg = update_check.maybe_check_for_updates("1.0.0", repo="x/y")
    assert mock_fetch.call_count == 0
    assert msg is not None  # uses cached "latest"


def test_cache_expires_after_24h(isolated_state):
    state_file = isolated_state / "last_update_check.json"
    state_file.write_text(json.dumps({
        "checked_at": int(time.time()) - 25 * 3600,  # 25 hours ago
        "latest": "1.4.0",
    }))
    with patch("wsp.update_check._fetch_latest_via_gh", return_value="v1.5.0") as mock_fetch:
        msg = update_check.maybe_check_for_updates("1.0.0", repo="x/y")
    assert mock_fetch.call_count == 1
    assert "1.5.0" in msg


def test_fetch_failure_swallowed_silently(isolated_state):
    with patch("wsp.update_check._fetch_latest_via_gh", return_value=None):
        msg = update_check.maybe_check_for_updates("1.0.0", repo="x/y")
    assert msg is None
    state_file = isolated_state / "last_update_check.json"
    assert state_file.exists()  # ensure we don't retry every command


def test_major_version_behind_includes_changelog_pointer(isolated_state):
    with patch("wsp.update_check._fetch_latest_via_gh", return_value="v3.0.0"):
        msg = update_check.maybe_check_for_updates("1.0.0", repo="x/y")
    assert "CHANGELOG" in msg
    assert "major" in msg.lower()


def test_dev_install_unparseable_version_does_not_crash(isolated_state):
    # If __version__ is "0+local.dev", the parse returns None and we treat
    # it as "we don't know, skip".
    with patch("wsp.update_check._fetch_latest_via_gh", return_value="v1.4.0"):
        msg = update_check.maybe_check_for_updates("0+local.dev", repo="x/y")
    assert msg is None


def test_force_bypasses_cache(isolated_state):
    state_file = isolated_state / "last_update_check.json"
    state_file.write_text(json.dumps({
        "checked_at": int(time.time()) - 60,
        "latest": "1.4.0",
    }))
    with patch("wsp.update_check._fetch_latest_via_gh", return_value="v1.5.0") as mock_fetch:
        msg = update_check.maybe_check_for_updates("1.0.0", repo="x/y", force=True)
    assert mock_fetch.call_count == 1
    assert "1.5.0" in msg
