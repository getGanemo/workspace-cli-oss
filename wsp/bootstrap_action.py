"""The high-level `wsp bootstrap` action.

Resolves the active stacks, clones them and the product repos they declare,
composes `.agents/`, regenerates CLAUDE.md / AGENTS.md, and writes
`workspace.lock.yml`.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from wsp import __version__ as WSP_VERSION
from wsp import composer, git_ops
from wsp.manifest import (
    ExtraRepo,
    Manifest,
    StackEntry,
    load_stack_awac,
)
from wsp.registry import Registry, StackRef


@dataclass
class StackResolution:
    label: str
    ref: StackRef
    branch: str
    commit: str | None = None
    cache_path: Path | None = None


@dataclass
class RepoResolution:
    full: str
    branch: str
    workspace_path: str
    commit: str | None = None
    source_stack: str | None = None


@dataclass
class BootstrapResult:
    stacks: list[StackResolution] = field(default_factory=list)
    repos: list[RepoResolution] = field(default_factory=list)
    canonical: str = ""
    mirrors: list[str] = field(default_factory=list)
    agent_dirs: list[str] = field(default_factory=list)
    file_count: int = 0
    collisions: list[dict[str, str]] = field(default_factory=list)
    lock_path: str = ""

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
            "repos": [
                {
                    "repo": r.full,
                    "branch": r.branch,
                    "path": r.workspace_path,
                    "commit": r.commit,
                    "source_stack": r.source_stack,
                }
                for r in self.repos
            ],
            "agent_files": {
                "canonical": self.canonical,
                "mirrors": self.mirrors,
            },
            "agent_dirs": self.agent_dirs,
            "file_count": self.file_count,
            "collisions": self.collisions,
            "lock": self.lock_path,
        }


def _resolve_module_repos(
    stack_entry: StackEntry,
    erp_partners_module_convention: dict[str, Any] | None,
) -> list[ExtraRepo]:
    """Turn an `org/modules` stack block into per-module ExtraRepos."""
    out: list[ExtraRepo] = []
    org = stack_entry.odoo_org or "erp-partners"
    conv = erp_partners_module_convention or {}
    path_prefix = conv.get("path_prefix", "addons/")
    branch_default = conv.get("branch_default", "19-dev")
    repo_pattern = conv.get("repo_pattern", "{module_name}")
    for m in stack_entry.odoo_modules:
        repo_name = repo_pattern.format(module_name=m)
        out.append(
            ExtraRepo(
                org=org,
                repo=repo_name,
                branch=branch_default,
                path=f"{path_prefix}{m}",
            )
        )
    return out


def _path_for_stack_repo(repo_decl: dict[str, Any], default_org: str) -> tuple[str, str, str, str]:
    """Return (org, repo_name, branch, workspace_path) for a stack-declared repo."""
    name = repo_decl["name"]
    org = repo_decl.get("org", default_org)
    branch = repo_decl.get("branch_default", "main")
    path = repo_decl.get("path", f"{name}/")
    return org, name, branch, path


def run_bootstrap(workspace_root: Path, manifest: Manifest, registry: Registry) -> BootstrapResult:
    workspace_root = Path(workspace_root).resolve()
    result = BootstrapResult()

    odoo_module_convention: dict[str, Any] | None = None
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
            local, gres = git_ops.ensure_repo(ref.org, ref.repo)
            sa = load_stack_awac(local)
            if sa.module_convention:
                odoo_module_convention = sa.module_convention
            stacks_to_compose.append((label, local))
            result.stacks.append(
                StackResolution(label=label, ref=ref, branch="main", commit=gres.commit, cache_path=local)
            )
            for mod_repo in _resolve_module_repos(entry, odoo_module_convention):
                manifest.extra_repos.append(mod_repo)
            continue

        ref = registry.resolve(entry.ref)
        label = entry.ref if "/" not in entry.ref else ref.full
        local, gres = git_ops.ensure_repo(ref.org, ref.repo)
        sa = load_stack_awac(local)
        if sa.module_convention:
            odoo_module_convention = sa.module_convention
        stacks_to_compose.append((label, local))
        result.stacks.append(
            StackResolution(label=label, ref=ref, branch="main", commit=gres.commit, cache_path=local)
        )

        for repo_decl in sa.repos:
            org, repo_name, branch, path = _path_for_stack_repo(repo_decl, default_org=ref.org)
            full = f"{org}/{repo_name}"
            dest = workspace_root / path
            gres_repo = git_ops.clone_into(org, repo_name, branch, dest)
            result.repos.append(
                RepoResolution(
                    full=full,
                    branch=branch,
                    workspace_path=path,
                    commit=gres_repo.commit,
                    source_stack=label,
                )
            )

    if manifest.modules:
        for m in manifest.modules:
            conv = odoo_module_convention or {}
            org = conv.get("default_org", "erp-partners")
            branch = conv.get("branch_default", "19-dev")
            path_prefix = conv.get("path_prefix", "addons/")
            dest = workspace_root / f"{path_prefix}{m}"
            gres_repo = git_ops.clone_into(org, m, branch, dest)
            result.repos.append(
                RepoResolution(
                    full=f"{org}/{m}",
                    branch=branch,
                    workspace_path=f"{path_prefix}{m}",
                    commit=gres_repo.commit,
                    source_stack="modules",
                )
            )

    for extra in manifest.extra_repos:
        path = extra.path or f"{extra.repo}/"
        dest = workspace_root / path
        gres_repo = git_ops.clone_into(extra.org, extra.repo, extra.branch, dest)
        result.repos.append(
            RepoResolution(
                full=extra.full,
                branch=extra.branch,
                workspace_path=path,
                commit=gres_repo.commit,
                source_stack="extra_repos",
            )
        )

    compose_report = composer.compose_agents(workspace_root, stacks_to_compose)
    result.agent_dirs = compose_report.agent_dirs_written
    result.file_count = compose_report.file_count
    result.collisions = compose_report.collisions

    canonical = (manifest.agent_context_override or registry.agent_context or {}).get("canonical", "CLAUDE.md")
    mirrors = (manifest.agent_context_override or registry.agent_context or {}).get("mirrors", ["AGENTS.md"])
    stacks_summary = [
        {
            "label": s.label,
            "repo": s.ref.full,
            "ref": s.branch,
            "commit": s.commit or "",
        }
        for s in result.stacks
    ]
    repos_summary = "\n".join(
        f"- `{r.full}@{r.branch}` → `{r.workspace_path}`" for r in result.repos
    ) if result.repos else None

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

    lock = {
        "schema": "awac/1",
        "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "wsp_version": WSP_VERSION,
        "stacks": [
            {"repo": s.ref.full, "ref": s.branch, "commit": s.commit}
            for s in result.stacks
        ],
        "repos": [
            {"repo": r.full, "ref": r.branch, "commit": r.commit, "path": r.workspace_path}
            for r in result.repos
        ],
    }
    lock_path = workspace_root / "workspace.lock.yml"
    lock_path.write_text(
        "# Generated by wsp. Do not edit by hand.\n"
        + yaml.safe_dump(lock, sort_keys=False),
        encoding="utf-8",
    )
    result.lock_path = str(lock_path)
    return result
