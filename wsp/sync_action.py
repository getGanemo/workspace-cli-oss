"""The high-level `wsp sync` action.

Refresh stacks (rules/skills/workflows) and regenerate CLAUDE.md/AGENTS.md
*without* re-cloning the product repos that live in the workspace.

Difference vs `bootstrap`:
  - bootstrap pulls stacks AND clones/pulls each declared product repo into
    the workspace AND regenerates the lockfile (stacks + repos).
  - sync only pulls stacks (cache) AND recomposes `.agents/` AND regenerates
    CLAUDE.md/AGENTS.md AND updates the lockfile's `stacks:` block.
    The `repos:` block of the lockfile is preserved untouched.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from wsp import __version__ as WSP_VERSION
from wsp import composer, errors, git_ops
from wsp.bootstrap_action import StackResolution, materialize_stack_metadata
from wsp.manifest import Manifest, load_stack_awac
from wsp.registry import Registry, StackRef


@dataclass
class SyncResult:
    stacks: list[StackResolution] = field(default_factory=list)
    canonical: str = ""
    mirrors: list[str] = field(default_factory=list)
    agent_dirs: list[str] = field(default_factory=list)
    file_count: int = 0
    collisions: list[dict[str, str]] = field(default_factory=list)
    lock_path: str = ""
    repos_kept: int = 0
    stack_metadata: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stacks": [
                {
                    "label": s.label,
                    "repo": s.ref.full,
                    "branch": s.branch,
                    "commit": s.commit,
                }
                for s in self.stacks
            ],
            "agent_files": {
                "canonical": self.canonical,
                "mirrors": self.mirrors,
            },
            "agent_dirs": self.agent_dirs,
            "file_count": self.file_count,
            "collisions": self.collisions,
            "lock": self.lock_path,
            "repos_kept": self.repos_kept,
            "stack_metadata": list(self.stack_metadata),
        }


def _read_existing_lock(workspace_root: Path) -> dict[str, Any] | None:
    lock_path = workspace_root / "workspace.lock.yml"
    if not lock_path.exists():
        return None
    try:
        data = yaml.safe_load(lock_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else None


def _stack_repos_summary_lines(stacks: list[tuple[str, Path]]) -> list[str]:
    """Lines like '- `org/repo@branch` -> `path/`' from cached stack awac.yml."""
    lines: list[str] = []
    seen: set[str] = set()
    for label, root in stacks:
        sa = load_stack_awac(root)
        for repo_decl in sa.repos:
            org = repo_decl.get("org")
            name = repo_decl.get("name")
            if not org or not name:
                continue
            full = f"{org}/{name}"
            if full in seen:
                continue
            seen.add(full)
            branch = repo_decl.get("branch_default", "main")
            path = repo_decl.get("path", f"{name}/")
            lines.append(f"- `{full}@{branch}` → `{path}`")
    return lines


def run_sync(workspace_root: Path, manifest: Manifest, registry: Registry) -> SyncResult:
    workspace_root = Path(workspace_root).resolve()
    result = SyncResult()

    stacks_to_compose: list[tuple[str, Path]] = []
    for entry in manifest.stacks:
        if entry.is_odoo_modules:
            shortcut = entry.odoo_org if entry.odoo_org in registry.shortcuts else None
            ref = (
                registry.resolve(entry.odoo_org)
                if entry.odoo_org in registry.shortcuts
                else StackRef(org=entry.odoo_org, repo="agent-stack")
            )
            label = shortcut or ref.full
        else:
            ref = registry.resolve(entry.ref)
            label = entry.ref if "/" not in entry.ref else ref.full

        local, gres = git_ops.ensure_repo(ref.org, ref.repo)
        stacks_to_compose.append((label, local))
        result.stacks.append(
            StackResolution(label=label, ref=ref, branch="main", commit=gres.commit, cache_path=local)
        )
        sa = load_stack_awac(local)
        if sa.product:
            result.stack_metadata.extend(
                materialize_stack_metadata(
                    workspace_root,
                    product=sa.product,
                    cache_path=local,
                    source_repo=ref.full,
                    source_commit=gres.commit,
                )
            )

    compose_report = composer.compose_agents(workspace_root, stacks_to_compose)
    result.agent_dirs = compose_report.agent_dirs_written
    result.file_count = compose_report.file_count
    result.collisions = compose_report.collisions

    canonical = (manifest.agent_context_override or registry.agent_context or {}).get("canonical", "CLAUDE.md")
    mirrors = (manifest.agent_context_override or registry.agent_context or {}).get("mirrors", ["AGENTS.md"])
    stacks_summary = [
        {"label": s.label, "repo": s.ref.full, "ref": s.branch, "commit": s.commit or ""}
        for s in result.stacks
    ]

    existing_lock = _read_existing_lock(workspace_root)
    if existing_lock and existing_lock.get("repos"):
        repo_lines = [
            f"- `{r['repo']}@{r['ref']}` → `{r['path']}`"
            for r in existing_lock["repos"]
            if isinstance(r, dict) and r.get("repo") and r.get("ref") and r.get("path")
        ]
        result.repos_kept = len(repo_lines)
    else:
        repo_lines = _stack_repos_summary_lines(stacks_to_compose)
        result.repos_kept = 0
    repos_summary = "\n".join(repo_lines) if repo_lines else None

    written_canonical, mirrors_written = composer.write_agent_files(
        workspace_root=workspace_root,
        canonical_name=canonical,
        mirror_names=mirrors,
        workspace_name=manifest.name,
        stacks_summary=stacks_summary,
        repos_summary=repos_summary,
    )
    result.canonical = written_canonical
    result.mirrors = mirrors_written

    lock_schema = "awac/2" if result.stack_metadata else "awac/1"
    lock: dict[str, Any] = {
        "schema": lock_schema,
        "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "wsp_version": WSP_VERSION,
        "stacks": [
            {"repo": s.ref.full, "ref": s.branch, "commit": s.commit}
            for s in result.stacks
        ],
        "repos": (existing_lock or {}).get("repos", []),
    }
    if result.stack_metadata:
        lock["stack_metadata"] = result.stack_metadata
    lock_path = workspace_root / "workspace.lock.yml"
    lock_path.write_text(
        "# Generated by wsp. Do not edit by hand.\n"
        + yaml.safe_dump(lock, sort_keys=False),
        encoding="utf-8",
    )
    result.lock_path = str(lock_path)
    return result
