"""The high-level `wsp status` action.

Diff the workspace against `workspace.lock.yml`. Surfaces:
  - stacks: behind/ahead vs upstream relative to the lockfile commit.
  - repos: per cloned product repo — exists, dirty (uncommitted), HEAD commit
    vs lockfile commit, ahead/behind vs upstream branch.
  - agents_drift: files in `.agents/` that don't match any source stack
    (extraneous) or whose content was modified since composition.

Read-only: never mutates the workspace, the cache, or any remote.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from wsp import errors, git_ops
from wsp.composer import AGENT_DIRS


@dataclass
class StackStatus:
    label: str
    repo: str
    ref: str
    lockfile_commit: str | None
    cache_head: str | None
    upstream_commit: str | None
    behind: int
    ahead: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "repo": self.repo,
            "ref": self.ref,
            "lockfile_commit": self.lockfile_commit,
            "cache_head": self.cache_head,
            "upstream_commit": self.upstream_commit,
            "behind": self.behind,
            "ahead": self.ahead,
            "in_sync": self.behind == 0 and self.ahead == 0
            and self.lockfile_commit == self.upstream_commit,
        }


@dataclass
class RepoStatus:
    repo: str
    path: str
    ref: str
    exists: bool
    is_git: bool
    lockfile_commit: str | None
    head_commit: str | None
    branch: str | None
    modified: list[str]
    behind: int
    ahead: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "repo": self.repo,
            "path": self.path,
            "ref": self.ref,
            "exists": self.exists,
            "is_git": self.is_git,
            "lockfile_commit": self.lockfile_commit,
            "head_commit": self.head_commit,
            "branch": self.branch,
            "modified": self.modified,
            "modified_count": len(self.modified),
            "behind": self.behind,
            "ahead": self.ahead,
            "matches_lock": self.head_commit == self.lockfile_commit and not self.modified,
        }


@dataclass
class AgentDriftItem:
    file: str
    reason: str  # "extraneous" | "modified"

    def to_dict(self) -> dict[str, Any]:
        return {"file": self.file, "reason": self.reason}


@dataclass
class StatusResult:
    stacks: list[StackStatus] = field(default_factory=list)
    repos: list[RepoStatus] = field(default_factory=list)
    agents_drift: list[AgentDriftItem] = field(default_factory=list)
    lock_path: str = ""
    has_lock: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "lock": self.lock_path,
            "has_lock": self.has_lock,
            "stacks": [s.to_dict() for s in self.stacks],
            "repos": [r.to_dict() for r in self.repos],
            "agents_drift": [d.to_dict() for d in self.agents_drift],
            "summary": {
                "stacks_out_of_sync": sum(1 for s in self.stacks if not s.to_dict()["in_sync"]),
                "repos_dirty_or_drifted": sum(1 for r in self.repos if not r.to_dict()["matches_lock"]),
                "agents_drift_count": len(self.agents_drift),
            },
        }


def _read_lock(workspace_root: Path) -> dict[str, Any] | None:
    lock_path = workspace_root / "workspace.lock.yml"
    if not lock_path.exists():
        return None
    try:
        data = yaml.safe_load(lock_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else None


def _stack_status_for_lock_entry(entry: dict[str, Any]) -> StackStatus:
    repo_full = entry.get("repo", "")
    ref = entry.get("ref", "main")
    lock_commit = entry.get("commit")
    org, _, repo = repo_full.partition("/")
    label = entry.get("label") or repo_full

    cache = git_ops.cache_path(org, repo)
    cache_head: str | None = None
    upstream: str | None = None
    behind = 0
    ahead = 0

    if cache.exists() and (cache / ".git").exists():
        git_ops.fetch_only(cache)
        cache_head = git_ops.head_commit(cache)
        upstream = git_ops.remote_commit(cache, ref)
        if lock_commit and upstream:
            behind, ahead = git_ops.commit_distance(cache, lock_commit, upstream)

    return StackStatus(
        label=label,
        repo=repo_full,
        ref=ref,
        lockfile_commit=lock_commit,
        cache_head=cache_head,
        upstream_commit=upstream,
        behind=behind,
        ahead=ahead,
    )


def _repo_status_for_lock_entry(workspace_root: Path, entry: dict[str, Any]) -> RepoStatus:
    repo_full = entry.get("repo", "")
    ref = entry.get("ref", "main")
    lock_commit = entry.get("commit")
    rel_path = entry.get("path", "")

    abs_path = (workspace_root / rel_path).resolve()
    exists = abs_path.exists()
    is_git = exists and (abs_path / ".git").exists()

    head: str | None = None
    branch: str | None = None
    modified: list[str] = []
    behind = 0
    ahead = 0

    if is_git:
        git_ops.fetch_only(abs_path)
        head = git_ops.head_commit(abs_path)
        branch = git_ops.current_branch(abs_path)
        modified = git_ops.porcelain_status(abs_path)
        upstream = git_ops.remote_commit(abs_path, ref)
        if upstream and head:
            behind, ahead = git_ops.commit_distance(abs_path, upstream, head)
            # commit_distance(base=upstream, head=local) -> (commits in upstream-not-local, commits in local-not-upstream)
            # = (behind, ahead) from local's POV.

    return RepoStatus(
        repo=repo_full,
        path=rel_path,
        ref=ref,
        exists=exists,
        is_git=is_git,
        lockfile_commit=lock_commit,
        head_commit=head,
        branch=branch,
        modified=modified,
        behind=behind,
        ahead=ahead,
    )


def _stack_source_files(stack_root: Path) -> dict[str, Path]:
    """Return {relative posix path under stack_root: absolute file path}."""
    out: dict[str, Path] = {}
    for sub in AGENT_DIRS:
        src = stack_root / sub
        if not src.exists() or not src.is_dir():
            continue
        for item in src.rglob("*"):
            if item.is_file():
                rel = item.relative_to(stack_root).as_posix()
                out[rel] = item
    return out


def _agent_drift(workspace_root: Path, stacks_in_lock: list[dict[str, Any]]) -> list[AgentDriftItem]:
    """Compare workspace `.agents/` against the union of cached stacks.

    last-stack-wins resolution (matches composer): for each rel path, the
    expected source is the last stack in lock order that has that file.
    """
    agents_dir = workspace_root / ".agents"
    if not agents_dir.exists():
        return []

    # build expected map honoring last-wins
    expected: dict[str, Path] = {}
    for entry in stacks_in_lock:
        repo_full = entry.get("repo", "")
        org, _, repo = repo_full.partition("/")
        cache = git_ops.cache_path(org, repo)
        if not cache.exists():
            continue
        files = _stack_source_files(cache)
        for rel, src in files.items():
            expected[rel] = src  # last stack wins

    drift: list[AgentDriftItem] = []
    for sub in AGENT_DIRS:
        sub_dir = agents_dir / sub
        if not sub_dir.exists():
            continue
        for item in sub_dir.rglob("*"):
            if not item.is_file():
                continue
            rel = item.relative_to(agents_dir).as_posix()
            src = expected.get(rel)
            if src is None:
                drift.append(AgentDriftItem(file=rel, reason="extraneous"))
                continue
            try:
                if src.read_bytes() != item.read_bytes():
                    drift.append(AgentDriftItem(file=rel, reason="modified"))
            except OSError:
                drift.append(AgentDriftItem(file=rel, reason="modified"))
    return drift


def run_status(workspace_root: Path) -> StatusResult:
    workspace_root = Path(workspace_root).resolve()
    result = StatusResult()
    lock = _read_lock(workspace_root)
    result.lock_path = str(workspace_root / "workspace.lock.yml")
    result.has_lock = lock is not None
    if lock is None:
        return result

    for stack_entry in lock.get("stacks") or []:
        if isinstance(stack_entry, dict):
            result.stacks.append(_stack_status_for_lock_entry(stack_entry))

    for repo_entry in lock.get("repos") or []:
        if isinstance(repo_entry, dict):
            result.repos.append(_repo_status_for_lock_entry(workspace_root, repo_entry))

    result.agents_drift = _agent_drift(workspace_root, lock.get("stacks") or [])
    return result
