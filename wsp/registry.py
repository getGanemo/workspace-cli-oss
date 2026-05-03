"""Load and resolve the AWaC registry (shortcuts + templates + org-scaffold rules).

The registry lives in `<WSP_REGISTRY_REPO>/awac.yml`, default
`getGanemo/agent-stack-core-oss/awac.yml` on branch `main`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from wsp import errors, git_ops

DEFAULT_REGISTRY_REPO = "getGanemo/agent-stack-core-oss"
DEFAULT_REGISTRY_BRANCH = "main"


@dataclass
class Template:
    name: str
    description: str
    path: str  # e.g. "acme/agent-stack/templates/feature.yml"


@dataclass
class StackRef:
    """A resolved stack: full org/repo plus the shortcut alias if any."""

    org: str
    repo: str
    shortcut: str | None = None

    @property
    def full(self) -> str:
        return f"{self.org}/{self.repo}"


@dataclass
class Registry:
    raw: dict[str, Any]
    repo: str
    branch: str
    local_path: Path
    shortcuts: dict[str, str] = field(default_factory=dict)
    templates: list[Template] = field(default_factory=list)
    agent_context: dict[str, Any] = field(default_factory=dict)

    def resolve(self, token: str) -> StackRef:
        """Resolve a stacks: entry into a StackRef.

        - "core"             -> registry lookup
        - "org/repo"         -> literal
        """
        if "/" in token:
            org, repo = token.split("/", 1)
            return StackRef(org=org, repo=repo)
        if token not in self.shortcuts:
            raise errors.shortcut_unknown(token, sorted(self.shortcuts.keys()))
        full = self.shortcuts[token]
        org, repo = full.split("/", 1)
        return StackRef(org=org, repo=repo, shortcut=token)

    def template(self, name: str) -> Template:
        for t in self.templates:
            if t.name == name:
                return t
        raise errors.template_unknown(name, [t.name for t in self.templates])


def registry_repo_and_branch() -> tuple[str, str]:
    return (
        os.environ.get("WSP_REGISTRY_REPO", DEFAULT_REGISTRY_REPO),
        os.environ.get("WSP_REGISTRY_BRANCH", DEFAULT_REGISTRY_BRANCH),
    )


def load_registry() -> Registry:
    repo_full, branch = registry_repo_and_branch()
    org, repo = repo_full.split("/", 1)
    try:
        local, _ = git_ops.ensure_repo(org, repo, ref=branch)
    except errors.WspError as exc:
        raise errors.registry_fetch_failed(repo_full, branch, exc.details.get("stderr", "") if exc.details else "")
    awac_yml = local / "awac.yml"
    if not awac_yml.exists():
        raise errors.WspError(
            code="WSP_005",
            category="schema",
            cause=f"Registry repo {repo_full}@{branch} has no awac.yml.",
            remediation="Point WSP_REGISTRY_REPO at a stack repo with an awac.yml.",
        )
    raw = yaml.safe_load(awac_yml.read_text(encoding="utf-8")) or {}
    shortcuts = dict(raw.get("shortcuts") or {})
    templates = [
        Template(name=t["name"], description=t.get("description", ""), path=t["path"])
        for t in (raw.get("templates") or [])
    ]
    agent_context = dict(raw.get("agent_context") or {})
    return Registry(
        raw=raw,
        repo=repo_full,
        branch=branch,
        local_path=local,
        shortcuts=shortcuts,
        templates=templates,
        agent_context=agent_context,
    )


def fetch_template_text(registry: Registry, template: Template) -> str:
    """Read a template file from a stack repo, ensuring the stack is cached."""
    parts = template.path.split("/")
    if len(parts) < 3:
        raise errors.WspError(
            code="WSP_002",
            category="schema",
            cause=f"Template path '{template.path}' is malformed.",
            remediation="Expected '<org>/<repo>/<rest>'.",
        )
    org, repo = parts[0], parts[1]
    rest = "/".join(parts[2:])
    local, _ = git_ops.ensure_repo(org, repo)
    file_path = local / rest
    if not file_path.exists():
        raise errors.WspError(
            code="WSP_002",
            category="filesystem",
            cause=f"Template file not found: {template.path}.",
            remediation="Check the registry's templates: list points at an existing file.",
        )
    return file_path.read_text(encoding="utf-8")
