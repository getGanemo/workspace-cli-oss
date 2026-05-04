"""Tests that bootstrap materializes .stack/<product>/{...} with header + lock hashes."""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import patch

import yaml

from wsp import bootstrap_action
from wsp.git_ops import GitResult
from wsp.manifest import Manifest, StackEntry
from wsp.registry import Registry


def _make_registry() -> Registry:
    return Registry(
        raw={},
        repo="getGanemo/agent-stack-core-oss",
        branch="main",
        local_path=Path("/dev/null"),
        shortcuts={"demo": "demoorg/agent-stack"},
        templates=[],
        agent_context={"canonical": "CLAUDE.md", "mirrors": ["AGENTS.md"]},
    )


def _seed_stack(cache_root: Path, files: dict[str, str]) -> Path:
    stack = cache_root / "demoorg" / "agent-stack"
    stack.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        p = stack / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return stack


def test_bootstrap_materializes_stack_files_with_header_and_lock(tmp_path):
    devvault_body = "schema: devvault/1\nproduct: demo\nsecrets:\n  aws: aws/demo.yml\n"
    deploy_body = (
        "schema: deploy/2\nproduct: demo\ncomponents:\n"
        "  - name: api\n    target: manual\n"
    )
    awac_body = "product: demo\nrepos: []\n"
    readme_body = "# Demo agent-stack\n\nHello.\n"
    stack = _seed_stack(
        tmp_path / "cache",
        {
            "devvault.yml": devvault_body,
            "deploy.yml": deploy_body,
            "awac.yml": awac_body,
            "README.md": readme_body,
        },
    )

    workspace = tmp_path / "ws"
    workspace.mkdir()
    manifest = Manifest(name="demo", schema="awac/2", raw={}, stacks=[StackEntry(ref="demo")])
    reg = _make_registry()

    def fake_ensure_repo(org, repo, ref="main", base_url=None):
        return stack, GitResult(ok=True, commit="abc12345" * 5, stderr="")

    with patch("wsp.bootstrap_action.git_ops.ensure_repo", side_effect=fake_ensure_repo), \
         patch("wsp.bootstrap_action.git_ops.clone_into",
               return_value=GitResult(ok=True, commit="x", stderr="")):
        result = bootstrap_action.run_bootstrap(workspace, manifest, reg)

    # 4 files materialized
    files_by_name = {Path(e["file"]).name for e in result.stack_metadata}
    assert files_by_name == {"README.md", "awac.yml", "devvault.yml", "deploy.yml"}

    # Header present in materialized files
    materialized = (workspace / ".stack/demo/devvault.yml").read_text(encoding="utf-8")
    assert "SYNCED FROM" in materialized
    assert "demoorg/agent-stack" in materialized
    # Body still present after the header
    assert devvault_body in materialized

    # Hash is over the original body (post-header)
    expected_hash = hashlib.sha256(devvault_body.encode("utf-8")).hexdigest()
    by_file = {Path(e["file"]).name: e for e in result.stack_metadata}
    assert by_file["devvault.yml"]["sha256"] == expected_hash

    # Lock includes stack_metadata + bumps schema to awac/2
    lock = yaml.safe_load((workspace / "workspace.lock.yml").read_text(encoding="utf-8"))
    assert lock["schema"] == "awac/2"
    assert "stack_metadata" in lock
    assert len(lock["stack_metadata"]) == 4

    # Markdown header form for README.md
    readme_mat = (workspace / ".stack/demo/README.md").read_text(encoding="utf-8")
    assert readme_mat.startswith("<!--")
    assert "SYNCED FROM" in readme_mat
    assert readme_body in readme_mat


def test_bootstrap_no_product_no_materialization(tmp_path):
    """Stacks without a product (transversal stacks) don't get .stack/ entries."""
    stack = _seed_stack(
        tmp_path / "cache",
        {"awac.yml": "scope: transversal\n"},
    )
    workspace = tmp_path / "ws"
    workspace.mkdir()
    manifest = Manifest(name="demo", schema="awac/1", raw={}, stacks=[StackEntry(ref="demo")])
    reg = _make_registry()

    with patch("wsp.bootstrap_action.git_ops.ensure_repo",
               return_value=(stack, GitResult(ok=True, commit="abc", stderr=""))), \
         patch("wsp.bootstrap_action.git_ops.clone_into",
               return_value=GitResult(ok=True, commit="x", stderr="")):
        result = bootstrap_action.run_bootstrap(workspace, manifest, reg)

    assert result.stack_metadata == []
    lock = yaml.safe_load((workspace / "workspace.lock.yml").read_text(encoding="utf-8"))
    assert lock["schema"] == "awac/1"
    assert "stack_metadata" not in lock
