"""Tests for workspace deploy_overrides merging into the resolved plan."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from wsp import deploy_action, errors, git_ops


def _seed_stack_with_deploy(cache_root: Path, product: str, deploy: dict) -> Path:
    """Create a fake cached stack and write its deploy.yml."""
    stack = cache_root / product / "agent-stack"
    stack.mkdir(parents=True, exist_ok=True)
    (stack / "deploy.yml").write_text(yaml.safe_dump(deploy, sort_keys=False), encoding="utf-8")
    return stack


def _patch_resolve(stack_path: Path, monkeypatch):
    monkeypatch.setattr(deploy_action, "_resolve_spec_path", lambda product: stack_path / "deploy.yml")


def test_workspace_override_replaces_odoo_sh_project(tmp_path, monkeypatch):
    deploy = {
        "schema": "deploy/2",
        "product": "demo",
        "components": [
            {
                "name": "A",
                "target": "odoo_sh",
                "odoo_sh": {"project": "prod-X", "branch": "main"},
            }
        ],
    }
    stack = _seed_stack_with_deploy(tmp_path / "cache", "demo", deploy)
    _patch_resolve(stack, monkeypatch)

    overrides = {"A": {"odoo_sh": {"project": "staging-X"}}}
    result = deploy_action.run_deploy_plan("demo", None, overrides)

    assert len(result.components) == 1
    c = result.components[0]
    assert c.target_block["project"] == "staging-X"
    assert c.target_block["branch"] == "main"  # untouched
    assert c.workspace_override_applied is True
    assert "odoo_sh" in c.overridden_fields


def test_workspace_override_skip_excludes_component(tmp_path, monkeypatch):
    deploy = {
        "schema": "deploy/2",
        "product": "demo",
        "components": [
            {"name": "A", "target": "manual"},
            {"name": "B", "target": "manual"},
        ],
    }
    stack = _seed_stack_with_deploy(tmp_path / "cache", "demo", deploy)
    _patch_resolve(stack, monkeypatch)

    overrides = {"A": {"skip": True}}
    result = deploy_action.run_deploy_plan("demo", None, overrides)

    names = [c.name for c in result.components]
    assert "A" not in names
    assert "B" in names


def test_workspace_override_target_outside_targets_available_raises_019(tmp_path, monkeypatch):
    deploy = {
        "schema": "deploy/2",
        "product": "demo",
        "components": [
            {
                "name": "A",
                "target": "odoo_sh",
                "targets_available": ["odoo_sh", "manual"],
            }
        ],
    }
    stack = _seed_stack_with_deploy(tmp_path / "cache", "demo", deploy)
    _patch_resolve(stack, monkeypatch)

    overrides = {"A": {"target": "aws_ecs"}}
    with pytest.raises(errors.WspError) as exc:
        deploy_action.run_deploy_plan("demo", None, overrides)
    assert exc.value.code == "WSP_019"


def test_workspace_override_target_inside_targets_available_passes(tmp_path, monkeypatch):
    deploy = {
        "schema": "deploy/2",
        "product": "demo",
        "components": [
            {
                "name": "A",
                "target": "odoo_sh",
                "targets_available": ["odoo_sh", "manual"],
            }
        ],
    }
    stack = _seed_stack_with_deploy(tmp_path / "cache", "demo", deploy)
    _patch_resolve(stack, monkeypatch)

    overrides = {"A": {"target": "manual"}}
    result = deploy_action.run_deploy_plan("demo", None, overrides)
    assert result.components[0].target == "manual"


def test_array_field_pre_steps_replaces_entirely(tmp_path, monkeypatch):
    deploy = {
        "schema": "deploy/2",
        "product": "demo",
        "components": [
            {
                "name": "A",
                "target": "manual",
                "pre_steps": ["a", "b"],
            }
        ],
    }
    stack = _seed_stack_with_deploy(tmp_path / "cache", "demo", deploy)
    _patch_resolve(stack, monkeypatch)

    overrides = {"A": {"pre_steps": ["only-this"]}}
    result = deploy_action.run_deploy_plan("demo", None, overrides)
    assert result.components[0].pre_steps == ["only-this"]


def test_no_overrides_yields_raw_stack_defaults(tmp_path, monkeypatch):
    deploy = {
        "schema": "deploy/2",
        "product": "demo",
        "components": [
            {"name": "A", "target": "odoo_sh", "odoo_sh": {"project": "prod-X"}},
        ],
    }
    stack = _seed_stack_with_deploy(tmp_path / "cache", "demo", deploy)
    _patch_resolve(stack, monkeypatch)

    result = deploy_action.run_deploy_plan("demo", None, None)
    assert result.components[0].target_block["project"] == "prod-X"
    assert result.components[0].workspace_override_applied is False
