"""The high-level `wsp bootstrap` action.

Resolves the active stacks, clones them and the product repos they declare,
composes `.agents/`, regenerates CLAUDE.md / AGENTS.md, and writes
`workspace.lock.yml`.
"""

from __future__ import annotations

import datetime as dt
import hashlib
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


STACK_METADATA_FILES = ("README.md", "awac.yml", "devvault.yml", "deploy.yml")


def _yaml_header(source_repo: str, commit: str | None) -> str:
    today = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    short = (commit or "unknown")[:8]
    return (
        "# ─────────────────────────────────────────────────────────────────────────\n"
        f"# SYNCED FROM {source_repo} on {today} (commit {short}).\n"
        "# This is a read-only mirror of the canonical file in the stack repo.\n"
        "# Edit the canonical version in the stack repo and run `wsp sync` to\n"
        "# refresh this mirror. `wsp doctor` reports if you edit this file\n"
        "# locally without syncing back to the stack.\n"
        "# For per-workspace variations (e.g. test environments), use\n"
        "# workspace.yml#deploy_overrides or #devvault_overrides instead.\n"
        "# ─────────────────────────────────────────────────────────────────────────\n"
    )


def _markdown_header(source_repo: str, commit: str | None) -> str:
    today = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    short = (commit or "unknown")[:8]
    return (
        "<!--\n"
        f"SYNCED FROM {source_repo} on {today} (commit {short}).\n"
        "This is a read-only mirror of the canonical file in the stack repo.\n"
        "Edit the canonical version in the stack repo and run `wsp sync` to\n"
        "refresh this mirror. `wsp doctor` reports if you edit this file\n"
        "locally without syncing back to the stack.\n"
        "For per-workspace variations (e.g. test environments), use\n"
        "workspace.yml#deploy_overrides or #devvault_overrides instead.\n"
        "-->\n"
    )


def _header_for(file_name: str, source_repo: str, commit: str | None) -> str:
    if file_name.endswith(".md"):
        return _markdown_header(source_repo, commit)
    return _yaml_header(source_repo, commit)


def _strip_synced_header(text: str) -> str:
    """Inverse of prepending a SYNCED-FROM header. Returns body POST-header.

    Recognises both YAML-comment and HTML-comment header forms. If no
    recognisable header is present, returns the original text untouched.
    """
    if not text:
        return text
    if text.startswith("<!--"):
        end = text.find("-->")
        if end != -1:
            after = text[end + 3 :]
            if after.startswith("\n"):
                after = after[1:]
            return after
        return text
    # YAML form: leading block of `#`-prefixed lines (header) + then content
    lines = text.split("\n")
    if not lines or not lines[0].startswith("#"):
        return text
    # Detect the SYNCED-FROM marker; if not present, do not strip.
    if not any("SYNCED FROM" in ln for ln in lines[:12]):
        return text
    # Strip the entire leading block of consecutive comment/blank lines.
    i = 0
    while i < len(lines) and (lines[i].startswith("#") or lines[i].strip() == ""):
        i += 1
    return "\n".join(lines[i:])


def materialize_stack_metadata(
    workspace_root: Path,
    product: str,
    cache_path: Path,
    source_repo: str,
    source_commit: str | None,
) -> list[dict[str, Any]]:
    """Copy stack metadata files into <workspace>/.stack/<product>/ with a header.

    Returns a list of lock entries for stack_metadata: dicts with keys
    {product, file, sha256, source_repo, source_commit}. The hash is over
    the original file body in the cache (not the header-prepended copy).
    """
    out: list[dict[str, Any]] = []
    target_dir = workspace_root / ".stack" / product
    target_dir.mkdir(parents=True, exist_ok=True)
    for fname in STACK_METADATA_FILES:
        src = cache_path / fname
        if not src.exists() or not src.is_file():
            continue
        body = src.read_text(encoding="utf-8")
        sha = hashlib.sha256(body.encode("utf-8")).hexdigest()
        header = _header_for(fname, source_repo, source_commit)
        target = target_dir / fname
        target.write_text(header + body, encoding="utf-8")
        out.append(
            {
                "product": product,
                "file": f".stack/{product}/{fname}",
                "sha256": sha,
                "source_repo": source_repo,
                "source_commit": source_commit or "",
            }
        )
    return out


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
            "stack_metadata": list(self.stack_metadata),
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

    lock_schema = "awac/2" if result.stack_metadata else "awac/1"
    lock: dict[str, Any] = {
        "schema": lock_schema,
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
