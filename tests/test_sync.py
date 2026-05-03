"""Unit tests for `wsp sync`. No network: stub registry + cached stacks on disk."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import yaml

from wsp import sync_action
from wsp.bootstrap_action import StackResolution
from wsp.git_ops import GitResult
from wsp.manifest import Manifest, StackEntry
from wsp.registry import Registry, StackRef


def _seed_stack(root: Path, files: dict[str, str], awac: dict | None = None) -> Path:
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    if awac is not None:
        (root / "awac.yml").write_text(yaml.safe_dump(awac, sort_keys=False), encoding="utf-8")
    return root


def _make_registry() -> Registry:
    return Registry(
        raw={},
        repo="getGanemo/agent-stack-core",
        branch="main",
        local_path=Path("/dev/null"),
        shortcuts={"core": "getGanemo/agent-stack-core"},
        templates=[],
        agent_context={"canonical": "CLAUDE.md", "mirrors": ["AGENTS.md"]},
    )


def test_sync_recomposes_agents_without_cloning_repos(tmp_path: Path):
    """sync should refresh .agents/ and never invoke clone_into."""
    cache_root = tmp_path / "cache"
    stack_a = _seed_stack(
        cache_root / "getGanemo" / "agent-stack-core",
        {"rules/a.md": "v2-content"},
        awac={"shortcuts": {}, "templates": []},
    )

    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "workspace.yml").write_text(
        yaml.safe_dump({"name": "demo", "schema": "awac/1", "stacks": ["core"]}),
        encoding="utf-8",
    )
    # Pre-existing lock with declared product repos that should NOT be touched.
    (workspace / "workspace.lock.yml").write_text(
        "schema: awac/1\nstacks: []\nrepos:\n"
        "  - {repo: acme/orchestrator, ref: main, commit: deadbeef, path: orchestrator/}\n",
        encoding="utf-8",
    )

    manifest = Manifest(
        name="demo",
        schema="awac/1",
        raw={},
        stacks=[StackEntry(ref="core")],
    )
    reg = _make_registry()

    def fake_ensure_repo(org, repo, ref="main", base_url=None):
        return stack_a, GitResult(ok=True, commit="abc1234567abc1234567abc1234567abc1234567", stderr="")

    clone_calls: list = []

    def fake_clone_into(org, repo, ref, dest, base_url=None):
        clone_calls.append((org, repo, ref, dest))
        return GitResult(ok=True, commit="never", stderr="")

    with patch("wsp.sync_action.git_ops.ensure_repo", side_effect=fake_ensure_repo), \
         patch("wsp.sync_action.git_ops.clone_into", side_effect=fake_clone_into):
        result = sync_action.run_sync(workspace, manifest, reg)

    assert result.file_count == 1
    assert (workspace / ".agents/rules/a.md").read_text() == "v2-content"
    # CLAUDE.md preserves the existing repo from the lock, no cloning happened.
    claude = (workspace / "CLAUDE.md").read_text()
    assert "acme/orchestrator" in claude
    assert clone_calls == []
    # Lock kept the repos block from the prior bootstrap.
    new_lock = yaml.safe_load((workspace / "workspace.lock.yml").read_text())
    assert any(r["repo"] == "acme/orchestrator" for r in new_lock["repos"])


def test_sync_falls_back_to_stack_awac_when_no_lock(tmp_path: Path):
    cache_root = tmp_path / "cache"
    stack = _seed_stack(
        cache_root / "getGanemo" / "agent-stack-core",
        {"workflows/x.md": "X"},
        awac={"repos": [{"name": "demo", "org": "myorg", "branch_default": "main", "path": "demo/"}]},
    )

    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "workspace.yml").write_text(
        yaml.safe_dump({"name": "demo", "schema": "awac/1", "stacks": ["core"]}),
        encoding="utf-8",
    )
    manifest = Manifest(name="demo", schema="awac/1", raw={}, stacks=[StackEntry(ref="core")])
    reg = _make_registry()

    with patch(
        "wsp.sync_action.git_ops.ensure_repo",
        return_value=(stack, GitResult(ok=True, commit="aa11", stderr="")),
    ):
        result = sync_action.run_sync(workspace, manifest, reg)

    assert result.repos_kept == 0
    assert "myorg/demo" in (workspace / "CLAUDE.md").read_text()
