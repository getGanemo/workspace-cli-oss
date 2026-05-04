"""High-level `wsp deploy <product> [--component <name>] [--plan]` action.

Reads `<product>/agent-stack/deploy.yml`, validates against schema deploy/1,
and prints the deploy plan. Actual deploy execution (push to Odoo.SH /
aws_ecs / cloudflare_pages) is delegated to the per-target topical workflows
in the agent assets — this command surfaces the spec + validates + plans.

In `--plan` mode (or default), the command exits without performing any
network mutation. To perform an actual deploy, an agent reads the printed
plan + the topical workflow corresponding to each `target` and executes
those steps. The CLI itself does NOT push to Odoo.SH or any other target —
that is intentional: the deploy logic is workflow-driven, not CLI-driven,
because each target's logic is too rich to encode generically here.

This keeps the CLI's responsibility tight: parse + validate + present.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

import jsonschema
import yaml

from wsp import errors, git_ops


@dataclass
class ComponentPlan:
    name: str
    target: str
    repo: str | None
    requires_human_approval: bool
    pre_steps: list[str]
    promote_after_pass: list[dict[str, Any]]
    target_block: dict[str, Any]
    rollback_window_minutes: int | None = None
    workspace_override_applied: bool = False
    overridden_fields: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "target": self.target,
            "repo": self.repo,
            "requires_human_approval": self.requires_human_approval,
            "pre_steps": self.pre_steps,
            "promote_after_pass": self.promote_after_pass,
            "target_block": self.target_block,
            "rollback_window_minutes": self.rollback_window_minutes,
            "workspace_override_applied": self.workspace_override_applied,
            "overridden_fields": list(self.overridden_fields),
        }


@dataclass
class DeployPlanResult:
    product: str
    spec_path: str
    components: list[ComponentPlan] = field(default_factory=list)
    validated: bool = False
    overrides_applied: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "product": self.product,
            "spec_path": self.spec_path,
            "validated": self.validated,
            "overrides_applied": self.overrides_applied,
            "components": [c.to_dict() for c in self.components],
        }


def _load_deploy_schema() -> dict:
    text = resources.files("wsp.schemas").joinpath("deploy.schema.json").read_text(encoding="utf-8")
    return json.loads(text)


def _resolve_spec_path(product: str) -> Path:
    """Resolve <product>/agent-stack/deploy.yml.

    Strategy: the cli lives at the user's machine; we don't have a workspace
    necessarily. We look up the product's agent-stack via the registry's
    shortcuts and read its deploy.yml from the cache.
    """
    from wsp.registry import load_registry, registry_repo_and_branch

    reg = load_registry()
    if product in reg.shortcuts:
        full = reg.shortcuts[product]
    else:
        full = f"{product}/agent-stack"
    org, repo = full.split("/", 1)
    cache, _ = git_ops.ensure_repo(org, repo)
    return cache / "deploy.yml"


SCALAR_OVERRIDE_FIELDS = (
    "target",
    "repo",
    "requires_human_approval",
    "rollback_window_minutes",
)
ARRAY_OVERRIDE_FIELDS = ("pre_steps", "promote_after_pass")
TARGET_BLOCK_KEYS = (
    "odoo_sh",
    "aws_ecs",
    "aws_lambda",
    "aws_ec2_ssm",
    "cloudflare_pages",
    "cloudflare_workers",
    "github_pages",
)


def _merge_component(
    stack_component: dict[str, Any],
    overrides: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Apply workspace overrides on top of a stack component.

    Returns (merged_component, overridden_field_names). Overridden field names
    only include fields that actually changed value (or were added).
    """
    merged: dict[str, Any] = dict(stack_component)
    changed: list[str] = []

    for field_name in SCALAR_OVERRIDE_FIELDS:
        if field_name in overrides:
            new_val = overrides[field_name]
            if merged.get(field_name) != new_val:
                changed.append(field_name)
            merged[field_name] = new_val

    for field_name in ARRAY_OVERRIDE_FIELDS:
        if field_name in overrides:
            new_val = list(overrides[field_name])
            if list(merged.get(field_name) or []) != new_val:
                changed.append(field_name)
            merged[field_name] = new_val

    for tk in TARGET_BLOCK_KEYS:
        if tk in overrides:
            stack_block = dict(merged.get(tk) or {})
            ws_block = overrides[tk] or {}
            if not isinstance(ws_block, dict):
                continue
            block_changed = False
            for k, v in ws_block.items():
                if stack_block.get(k) != v:
                    block_changed = True
                stack_block[k] = v
            merged[tk] = stack_block
            if block_changed:
                changed.append(tk)

    return merged, changed


def run_deploy_plan(
    product: str,
    component_name: str | None,
    workspace_overrides: dict[str, dict[str, Any]] | None = None,
) -> DeployPlanResult:
    spec_path = _resolve_spec_path(product)
    if not spec_path.exists():
        raise errors.WspError(
            code="WSP_022", category="filesystem",
            cause=f"No deploy.yml at {spec_path}.",
            remediation=(
                f"Author one with the `create_deploy_spec` skill in "
                f"getGanemo/agent-stack-core-oss/skills/. Spec lives at "
                f"<product>/agent-stack/deploy.yml."
            ),
            details={"path": str(spec_path), "product": product},
        )

    try:
        raw = yaml.safe_load(spec_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise errors.WspError(
            code="WSP_023", category="schema",
            cause=f"deploy.yml at {spec_path} is invalid YAML: {exc}",
            remediation="Fix YAML syntax.",
        )

    schema = _load_deploy_schema()
    try:
        jsonschema.validate(instance=raw, schema=schema)
    except jsonschema.ValidationError as exc:
        spec_schema = raw.get("schema", "deploy/?")
        raise errors.WspError(
            code="WSP_023", category="schema",
            cause=f"deploy.yml at {spec_path} fails schema {spec_schema}: {exc.message}",
            remediation="Run `wsp schema deploy` for the spec.",
            details={"path": str(spec_path), "json_path": list(exc.absolute_path)},
        )

    overrides = workspace_overrides or {}
    result = DeployPlanResult(
        product=raw.get("product", product),
        spec_path=str(spec_path),
        validated=True,
        overrides_applied=bool(overrides),
    )

    components = raw.get("components") or []
    if component_name:
        components = [c for c in components if c.get("name") == component_name]
        if not components:
            raise errors.WspError(
                code="WSP_024", category="input",
                cause=f"Component {component_name!r} not found in {spec_path}.",
                remediation="Run `wsp deploy <product> --plan` without --component to list them.",
            )

    for c in components:
        comp_name = c["name"]
        comp_overrides = overrides.get(comp_name) or {}
        if comp_overrides.get("skip") is True:
            # Excluded entirely.
            continue
        merged, overridden_fields = _merge_component(c, comp_overrides)

        target = merged["target"]
        # Validate against targets_available if set.
        targets_available = c.get("targets_available")
        if (
            "target" in overridden_fields
            and isinstance(targets_available, list)
            and target not in targets_available
        ):
            raise errors.override_target_not_available(
                component=comp_name,
                attempted_target=target,
                available=list(targets_available),
            )

        target_block = merged.get(target) or {}
        result.components.append(ComponentPlan(
            name=comp_name,
            target=target,
            repo=merged.get("repo"),
            requires_human_approval=merged.get("requires_human_approval", True),
            pre_steps=list(merged.get("pre_steps") or []),
            promote_after_pass=list(merged.get("promote_after_pass") or []),
            target_block=target_block,
            rollback_window_minutes=merged.get("rollback_window_minutes"),
            workspace_override_applied=bool(overridden_fields),
            overridden_fields=overridden_fields,
        ))
    return result
