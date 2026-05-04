"""Tests for `wsp migrate-deploy`."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import yaml
from click.testing import CliRunner

from wsp.cli import main
from wsp.git_ops import GitResult
from wsp.registry import Registry


def _seed_stack(cache_root: Path, deploy: dict) -> Path:
    stack = cache_root / "demoorg" / "agent-stack"
    stack.mkdir(parents=True, exist_ok=True)
    (stack / "deploy.yml").write_text(yaml.safe_dump(deploy, sort_keys=False), encoding="utf-8")
    return stack


def _patch_registry(monkeypatch):
    fake_reg = Registry(
        raw={}, repo="getGanemo/agent-stack-core-oss", branch="main",
        local_path=Path("/dev/null"),
        shortcuts={"demo": "demoorg/agent-stack"},
        templates=[], agent_context={},
    )
    monkeypatch.setattr("wsp.cli.registry.load_registry", lambda: fake_reg)


def test_migrate_v1_to_v2_adds_targets_available(tmp_path, monkeypatch):
    deploy_v1 = {
        "schema": "deploy/1",
        "product": "demo",
        "components": [
            {"name": "api", "target": "odoo_sh"},
            {"name": "infra", "target": "aws_ecs"},
        ],
    }
    stack = _seed_stack(tmp_path / "cache", deploy_v1)
    _patch_registry(monkeypatch)

    with patch("wsp.cli.git_ops.ensure_repo",
               return_value=(stack, GitResult(ok=True, commit="abc", stderr=""))):
        res = CliRunner().invoke(main, ["migrate-deploy", "demo", "--json"])

    assert res.exit_code == 0, res.output
    payload = json.loads(res.output)
    assert payload["component_count"] == 2
    assert payload["noop"] is False
    # Verify the cache was rewritten to v2
    rewritten = yaml.safe_load((stack / "deploy.yml").read_text(encoding="utf-8"))
    assert rewritten["schema"] == "deploy/2"
    by_name = {c["name"]: c for c in rewritten["components"]}
    assert by_name["api"]["targets_available"] == ["odoo_sh"]
    assert by_name["infra"]["targets_available"] == ["aws_ecs"]
    # Patched temp file exists and is also valid v2
    patched = yaml.safe_load(Path(payload["patched_path"]).read_text(encoding="utf-8"))
    assert patched["schema"] == "deploy/2"


def test_migrate_v2_is_noop(tmp_path, monkeypatch):
    deploy_v2 = {
        "schema": "deploy/2",
        "product": "demo",
        "components": [{"name": "api", "target": "manual"}],
    }
    stack = _seed_stack(tmp_path / "cache", deploy_v2)
    _patch_registry(monkeypatch)

    with patch("wsp.cli.git_ops.ensure_repo",
               return_value=(stack, GitResult(ok=True, commit="abc", stderr=""))):
        res = CliRunner().invoke(main, ["migrate-deploy", "demo", "--json"])

    payload = json.loads(res.output)
    assert payload["noop"] is True
