"""Parse and validate workspace.yml + each stack's awac.yml."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from wsp import errors

SUPPORTED_SCHEMAS = ["awac/1"]


@dataclass
class StackEntry:
    """One entry in workspace.yml/stacks: — a stack ref or an org+modules block."""

    ref: str | None = None  # shortcut or org/repo
    odoo_org: str | None = None  # if this entry is `org: ... modules: [...]`
    odoo_modules: list[str] = field(default_factory=list)

    @property
    def is_odoo_modules(self) -> bool:
        return self.odoo_org is not None


@dataclass
class ExtraRepo:
    org: str
    repo: str
    branch: str = "main"
    path: str | None = None  # workspace-relative target path

    @property
    def full(self) -> str:
        return f"{self.org}/{self.repo}"


@dataclass
class Manifest:
    name: str
    schema: str
    raw: dict[str, Any]
    stacks: list[StackEntry] = field(default_factory=list)
    extra_repos: list[ExtraRepo] = field(default_factory=list)
    modules: list[str] = field(default_factory=list)
    agent_context_override: dict[str, Any] | None = None
    path: Path | None = None


def find_workspace_yml(start: Path) -> Path:
    candidate = start / "workspace.yml"
    if candidate.exists():
        return candidate
    raise errors.manifest_missing(str(candidate))


def load_manifest(path: Path) -> Manifest:
    if not path.exists():
        raise errors.manifest_missing(str(path))
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise errors.manifest_invalid(f"YAML parse error: {exc}", str(path))
    if not isinstance(raw, dict):
        raise errors.manifest_invalid("Top-level must be a mapping.", str(path))

    name = raw.get("name")
    schema = raw.get("schema", "awac/1")
    if not name or not isinstance(name, str):
        raise errors.manifest_invalid("Missing or non-string 'name'.", str(path))
    if schema not in SUPPORTED_SCHEMAS:
        raise errors.schema_version_unsupported(schema, SUPPORTED_SCHEMAS)

    stacks: list[StackEntry] = []
    for entry in raw.get("stacks") or []:
        if isinstance(entry, str):
            stacks.append(StackEntry(ref=entry))
        elif isinstance(entry, dict):
            if "org" in entry and "modules" in entry:
                stacks.append(
                    StackEntry(
                        odoo_org=entry["org"],
                        odoo_modules=list(entry["modules"]),
                    )
                )
            elif "ref" in entry:
                stacks.append(StackEntry(ref=entry["ref"]))
            else:
                raise errors.manifest_invalid(
                    f"Stack entry must be a string, '{{ref: ...}}', or '{{org: ..., modules: [...]}}', got {entry!r}.",
                    str(path),
                )
        else:
            raise errors.manifest_invalid(
                f"Stack entry must be a string or mapping, got {type(entry).__name__}.",
                str(path),
            )

    modules = list(raw.get("modules") or [])

    extras: list[ExtraRepo] = []
    for entry in raw.get("extra_repos") or []:
        if not isinstance(entry, dict) or "org" not in entry or "repo" not in entry:
            raise errors.manifest_invalid(
                f"extra_repos entries need org+repo: got {entry!r}.",
                str(path),
            )
        extras.append(
            ExtraRepo(
                org=entry["org"],
                repo=entry["repo"],
                branch=entry.get("branch", "main"),
                path=entry.get("path"),
            )
        )

    agent_ctx = raw.get("agent_context")
    return Manifest(
        name=name,
        schema=schema,
        raw=raw,
        stacks=stacks,
        extra_repos=extras,
        modules=modules,
        agent_context_override=agent_ctx if isinstance(agent_ctx, dict) else None,
        path=path,
    )


@dataclass
class StackAwac:
    """Parsed `<stack>/awac.yml` for a product/transversal stack."""

    raw: dict[str, Any]
    product: str | None = None
    scope: str | None = None
    repos: list[dict[str, Any]] = field(default_factory=list)
    module_convention: dict[str, Any] | None = None


def load_stack_awac(stack_root: Path) -> StackAwac:
    awac_yml = stack_root / "awac.yml"
    if not awac_yml.exists():
        return StackAwac(raw={}, repos=[])
    try:
        raw = yaml.safe_load(awac_yml.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise errors.WspError(
            code="WSP_002",
            category="schema",
            cause=f"awac.yml in {stack_root} is invalid YAML: {exc}",
            remediation="Fix the YAML syntax.",
        )
    if not isinstance(raw, dict):
        raw = {}
    return StackAwac(
        raw=raw,
        product=raw.get("product"),
        scope=raw.get("scope"),
        repos=list(raw.get("repos") or []),
        module_convention=raw.get("module_convention"),
    )
