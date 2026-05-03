"""Unit tests for `wsp status`. Exercises agent drift + git inspection helpers
with stubbed git ops."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from wsp import git_ops, status_action


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def _init_repo(path: Path, files: dict[str, str], commit_msg: str = "init") -> str:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "t@t")
    _git(path, "config", "user.name", "t")
    for rel, content in files.items():
        full = path / rel
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", commit_msg)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(path), capture_output=True, text=True
    ).stdout.strip()
    return head


def test_status_no_lock_returns_empty(tmp_path: Path):
    (tmp_path / "workspace.yml").write_text("name: demo\n", encoding="utf-8")
    result = status_action.run_status(tmp_path)
    assert result.has_lock is False
    assert result.stacks == []
    assert result.repos == []
    assert result.agents_drift == []


def test_status_detects_dirty_repo_and_extraneous_drift(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "ws"
    workspace.mkdir()

    # Cache layout the status code expects: $WSP_CACHE_DIR/<org>/<repo>
    cache_root = tmp_path / "wspcache"
    monkeypatch.setenv("WSP_CACHE_DIR", str(cache_root))

    stack_repo = cache_root / "myorg" / "agent-stack-core"
    head_a = _init_repo(stack_repo, {"rules/a.md": "FROM-STACK\n"})

    # Workspace product repo (a real local git repo)
    product_repo = workspace / "product"
    head_p = _init_repo(product_repo, {"README.md": "hello\n"})

    # Mark workspace product as having uncommitted change
    (product_repo / "README.md").write_text("hello world\n", encoding="utf-8")

    # Compose the workspace .agents/: matches stack content + an extraneous file
    (workspace / ".agents/rules").mkdir(parents=True)
    (workspace / ".agents/rules/a.md").write_text("FROM-STACK\n", encoding="utf-8")
    (workspace / ".agents/rules/extra.md").write_text("not from any stack", encoding="utf-8")
    (workspace / ".agents/rules/modified.md").write_text("local-edit", encoding="utf-8")
    # Add a "modified" file that the stack actually has, to test the modified path
    (stack_repo / "rules/modified.md").write_text("ORIGINAL\n", encoding="utf-8")
    _git(stack_repo, "add", "-A")
    _git(stack_repo, "commit", "-q", "-m", "add modified.md")
    head_a2 = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(stack_repo), capture_output=True, text=True
    ).stdout.strip()

    (workspace / "workspace.yml").write_text("name: demo\n", encoding="utf-8")
    (workspace / "workspace.lock.yml").write_text(
        yaml.safe_dump(
            {
                "schema": "awac/1",
                "stacks": [{"repo": "myorg/agent-stack-core", "ref": "main", "commit": head_a2}],
                "repos": [
                    {"repo": "x/product", "ref": "main", "commit": head_p, "path": "product/"}
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    # No remote in the test, so fetch_only will fail — we accept that and assert
    # the in-process facts (lockfile vs HEAD, dirty status, drift).
    result = status_action.run_status(workspace)

    assert result.has_lock is True
    assert len(result.stacks) == 1
    s = result.stacks[0]
    assert s.lockfile_commit == head_a2
    # cache HEAD matches the lock (we just committed at that ref)
    assert s.cache_head == head_a2

    assert len(result.repos) == 1
    r = result.repos[0]
    assert r.exists is True
    assert r.is_git is True
    assert r.head_commit == head_p
    # Modified is detected
    assert any("README.md" in line for line in r.modified)
    # Lock matches HEAD but dirty workspace
    assert r.to_dict()["matches_lock"] is False

    drift_files = {(d.file, d.reason) for d in result.agents_drift}
    assert ("rules/extra.md", "extraneous") in drift_files
    assert ("rules/modified.md", "modified") in drift_files
    # Files that match a source stack are not in drift
    assert all(d.file != "rules/a.md" for d in result.agents_drift)


def test_commit_distance_helpers(tmp_path: Path):
    repo = tmp_path / "r"
    head_1 = _init_repo(repo, {"f": "1"})
    (repo / "f").write_text("2", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "second")
    head_2 = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(repo), capture_output=True, text=True
    ).stdout.strip()

    behind, ahead = git_ops.commit_distance(repo, head_1, head_2)
    # head_2 is one ahead of head_1
    assert behind == 0 and ahead == 1

    behind2, ahead2 = git_ops.commit_distance(repo, head_2, head_1)
    assert behind2 == 1 and ahead2 == 0

    assert git_ops.head_commit(repo) == head_2
    porcelain = git_ops.porcelain_status(repo)
    assert porcelain == []
    (repo / "f").write_text("3", encoding="utf-8")
    porcelain = git_ops.porcelain_status(repo)
    assert any("f" in ln for ln in porcelain)
