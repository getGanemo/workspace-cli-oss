"""Tests for the `wsp doctor` step `stack_metadata_drift`."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import yaml
from click.testing import CliRunner

from wsp.cli import main


def _write_lock(workspace: Path, body: str, sha: str) -> None:
    lock = {
        "schema": "awac/2",
        "generated_at": "2026-05-04T00:00:00Z",
        "stacks": [],
        "stack_metadata": [
            {
                "product": "demo",
                "file": ".stack/demo/devvault.yml",
                "sha256": sha,
                "source_repo": "demoorg/agent-stack",
                "source_commit": "abc",
            }
        ],
    }
    (workspace / "workspace.lock.yml").write_text(yaml.safe_dump(lock), encoding="utf-8")


def _write_materialized(workspace: Path, body: str) -> None:
    target = workspace / ".stack" / "demo" / "devvault.yml"
    target.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "# ─────────────────────────────────────────────────────────────────────────\n"
        "# SYNCED FROM demoorg/agent-stack on 2026-05-04 (commit abc).\n"
        "# header line.\n"
        "# ─────────────────────────────────────────────────────────────────────────\n"
    )
    target.write_text(header + body, encoding="utf-8")


def test_doctor_stack_metadata_in_sync_passes(tmp_path, monkeypatch):
    import hashlib
    body = "schema: devvault/1\nproduct: demo\nsecrets: {}\n"
    sha = hashlib.sha256(body.encode("utf-8")).hexdigest()

    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "workspace.yml").write_text("name: x\nschema: awac/2\nstacks: [core]\n", encoding="utf-8")
    _write_materialized(workspace, body)
    _write_lock(workspace, body, sha)

    monkeypatch.chdir(workspace)
    # Stub the network bits doctor would touch.
    with patch("wsp.cli.governance.run_governance_check") as gov:
        from wsp.governance import CheckResult
        gov.return_value = CheckResult(aligned=True, problems=[], awac_repo="x", governance_repo="y")
        with patch("wsp.cli.registry.load_registry") as reg:
            from wsp.errors import WspError
            reg.side_effect = WspError(code="WSP_005", category="network",
                                        cause="stub", remediation="stub")  # We don't care about registry; the wrapper catches.
            res = CliRunner().invoke(main, ["doctor", "--json"])
    data = json.loads(res.output)
    drift_check = next(c for c in data["checks"] if c["name"] == "stack_metadata_drift")
    assert drift_check["status"] == "ok"
    assert "in sync" in drift_check["info"]


def test_doctor_stack_metadata_drift_detected(tmp_path, monkeypatch):
    import hashlib
    body = "schema: devvault/1\nproduct: demo\nsecrets: {}\n"
    sha = hashlib.sha256(body.encode("utf-8")).hexdigest()

    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "workspace.yml").write_text("name: x\nschema: awac/2\nstacks: [core]\n", encoding="utf-8")
    _write_materialized(workspace, body)
    _write_lock(workspace, body, sha)

    # Mutate the materialized file body (drift)
    target = workspace / ".stack" / "demo" / "devvault.yml"
    text = target.read_text(encoding="utf-8")
    target.write_text(text + "\n# locally edited\n", encoding="utf-8")

    monkeypatch.chdir(workspace)
    with patch("wsp.cli.governance.run_governance_check") as gov:
        from wsp.governance import CheckResult
        gov.return_value = CheckResult(aligned=True, problems=[], awac_repo="x", governance_repo="y")
        with patch("wsp.cli.registry.load_registry") as reg:
            from wsp.errors import WspError
            reg.side_effect = WspError(code="WSP_005", category="network",
                                        cause="stub", remediation="stub")
            res = CliRunner().invoke(main, ["doctor", "--json"])
    data = json.loads(res.output)
    drift_check = next(c for c in data["checks"] if c["name"] == "stack_metadata_drift")
    assert drift_check["status"] == "fail"
    assert "drifted" in drift_check["info"] or "drifted" in drift_check["remediation"].lower()


def test_doctor_no_workspace_yields_ok(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with patch("wsp.cli.governance.run_governance_check") as gov:
        from wsp.governance import CheckResult
        gov.return_value = CheckResult(aligned=True, problems=[], awac_repo="x", governance_repo="y")
        with patch("wsp.cli.registry.load_registry") as reg:
            from wsp.errors import WspError
            reg.side_effect = WspError(code="WSP_005", category="network",
                                        cause="stub", remediation="stub")
            res = CliRunner().invoke(main, ["doctor", "--json"])
    data = json.loads(res.output)
    drift_check = next(c for c in data["checks"] if c["name"] == "stack_metadata_drift")
    assert drift_check["status"] == "ok"
    assert "no workspace" in drift_check["info"]
