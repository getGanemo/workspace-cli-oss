"""High-level `wsp secrets check <product>` action.

Reads `<product>/agent-stack/devvault.yml`, resolves each cataloged path
against `~/.devvault/.config.yml#vault_path`, and reports which secrets
are present on this machine.

Read-only: never prints secret values, never opens secret files beyond an
existence + readability check.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

import jsonschema
import yaml

from wsp import errors, git_ops


@dataclass
class SecretEntry:
    logical_name: str
    relative_path: str
    resolved_path: str
    exists: bool
    readable: bool
    workspace_override: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "logical_name": self.logical_name,
            "relative_path": self.relative_path,
            "resolved_path": self.resolved_path,
            "exists": self.exists,
            "readable": self.readable,
            "workspace_override": self.workspace_override,
        }


@dataclass
class SecretsCheckResult:
    product: str
    catalog_path: str
    vault_path: str
    entries: list[SecretEntry] = field(default_factory=list)

    @property
    def all_present(self) -> bool:
        return all(e.exists and e.readable for e in self.entries)

    def to_dict(self) -> dict[str, Any]:
        return {
            "product": self.product,
            "catalog_path": self.catalog_path,
            "vault_path": self.vault_path,
            "all_present": self.all_present,
            "entries": [e.to_dict() for e in self.entries],
            "summary": {
                "total": len(self.entries),
                "missing": sum(1 for e in self.entries if not e.exists),
                "unreadable": sum(1 for e in self.entries if e.exists and not e.readable),
            },
        }


def _load_devvault_schema() -> dict:
    text = resources.files("wsp.schemas").joinpath("devvault.schema.json").read_text(encoding="utf-8")
    return json.loads(text)


def _resolve_catalog_path(product: str) -> Path:
    from wsp.registry import load_registry

    reg = load_registry()
    if product in reg.shortcuts:
        full = reg.shortcuts[product]
    else:
        full = f"{product}/agent-stack"
    org, repo = full.split("/", 1)
    cache, _ = git_ops.ensure_repo(org, repo)
    return cache / "devvault.yml"


def _resolve_vault_path() -> Path:
    cfg_path = Path.home() / ".devvault" / ".config.yml"
    if not cfg_path.exists():
        raise errors.WspError(
            code="WSP_025", category="env",
            cause=f"~/.devvault/.config.yml not found.",
            remediation=(
                f"Create {cfg_path} with `vault_path: <absolute path>`. "
                "See the use_devvault rule in getGanemo/agent-stack-core-oss."
            ),
            details={"path": str(cfg_path)},
        )
    try:
        cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise errors.WspError(
            code="WSP_025", category="schema",
            cause=f"~/.devvault/.config.yml is invalid YAML: {exc}",
            remediation="Fix YAML syntax.",
        )
    vp = cfg.get("vault_path")
    if not vp:
        raise errors.WspError(
            code="WSP_025", category="schema",
            cause=f"~/.devvault/.config.yml has no vault_path key.",
            remediation="Add `vault_path: <absolute path>`.",
        )
    return Path(vp)


def run_secrets_check(
    product: str,
    workspace_overrides: dict[str, str] | None = None,
) -> SecretsCheckResult:
    catalog_path = _resolve_catalog_path(product)
    if not catalog_path.exists():
        raise errors.WspError(
            code="WSP_026", category="filesystem",
            cause=f"No devvault.yml at {catalog_path}.",
            remediation=(
                "Author one — schema devvault/1 (run `wsp schema devvault`). "
                "Lives at <product>/agent-stack/devvault.yml."
            ),
            details={"path": str(catalog_path), "product": product},
        )
    try:
        raw = yaml.safe_load(catalog_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise errors.WspError(
            code="WSP_026", category="schema",
            cause=f"devvault.yml at {catalog_path} invalid YAML: {exc}",
            remediation="Fix YAML syntax.",
        )

    schema = _load_devvault_schema()
    try:
        jsonschema.validate(instance=raw, schema=schema)
    except jsonschema.ValidationError as exc:
        raise errors.WspError(
            code="WSP_026", category="schema",
            cause=f"devvault.yml at {catalog_path} fails schema devvault/1: {exc.message}",
            remediation="Run `wsp schema devvault` for the spec.",
            details={"json_path": list(exc.absolute_path)},
        )

    vault_path = _resolve_vault_path()
    result = SecretsCheckResult(
        product=raw.get("product", product),
        catalog_path=str(catalog_path),
        vault_path=str(vault_path),
    )

    overrides = workspace_overrides or {}
    for logical_name, rel in (raw.get("secrets") or {}).items():
        is_override = logical_name in overrides
        effective_rel = overrides[logical_name] if is_override else rel
        resolved = vault_path / effective_rel
        exists = resolved.exists()
        readable = exists and os.access(resolved, os.R_OK)
        result.entries.append(SecretEntry(
            logical_name=logical_name,
            relative_path=effective_rel,
            resolved_path=str(resolved),
            exists=exists,
            readable=readable,
            workspace_override=is_override,
        ))

    return result
