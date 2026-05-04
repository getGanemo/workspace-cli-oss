"""Tests for `wsp guide`."""

from __future__ import annotations

import json

from click.testing import CliRunner

from wsp.cli import main


def test_guide_init_returns_non_empty_text():
    res = CliRunner().invoke(main, ["guide", "init"])
    assert res.exit_code == 0
    assert "init" in res.output.lower()
    assert len(res.output.strip()) > 200


def test_guide_no_topic_lists_topics():
    res = CliRunner().invoke(main, ["guide"])
    assert res.exit_code == 0
    for topic in ("init", "onboard-product", "deploy", "secrets", "discover"):
        assert topic in res.output


def test_guide_unknown_topic_returns_structured_error():
    res = CliRunner().invoke(main, ["guide", "nonexistent", "--json"])
    assert res.exit_code != 0
    payload = json.loads(res.output)
    assert payload["error"]["code"] == "WSP_010"


def test_guide_all_topics_have_text():
    from wsp.guides import GUIDE_TOPICS
    runner = CliRunner()
    for topic in GUIDE_TOPICS:
        res = runner.invoke(main, ["guide", topic])
        assert res.exit_code == 0, f"{topic} failed: {res.output}"
        assert len(res.output.strip()) > 100, f"{topic} too short"
