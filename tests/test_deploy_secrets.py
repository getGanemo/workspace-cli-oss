"""Unit tests for the deploy + secrets actions. Schema validation only —
network paths (resolving from registry cache) are exercised in integration."""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path

import jsonschema
import pytest


def _schema(name: str) -> dict:
    text = resources.files("wsp.schemas").joinpath(name).read_text(encoding="utf-8")
    return json.loads(text)


# ---- deploy/1 ----


def test_deploy_schema_accepts_minimal_aws_ecs():
    s = _schema("deploy.schema.json")
    spec = {
        "schema": "deploy/1",
        "product": "demo",
        "components": [
            {"name": "api", "target": "aws_ecs", "requires_human_approval": True}
        ],
    }
    jsonschema.validate(spec, s)


def test_deploy_schema_accepts_full_odoo_sh_with_promote():
    s = _schema("deploy.schema.json")
    spec = {
        "schema": "deploy/1",
        "product": "acme",
        "components": [
            {
                "name": "acme_portal_module",
                "target": "odoo_sh",
                "repo": "GanemoCorp/acme-portal-staging",
                "requires_human_approval": True,
                "pre_steps": ["run_odoo_tests_docker_wsl"],
                "odoo_sh": {
                    "project": "ganemocorp-acme-portal",
                    "branch": "main",
                    "module_scope": "list",
                    "modules": ["acme_portal"],
                },
                "promote_after_pass": [
                    {
                        "target_repo": "erp-partners/acme_portal",
                        "target_branch": "19.0",
                        "require_pass_on": "odoo_sh",
                    }
                ],
            }
        ],
    }
    jsonschema.validate(spec, s)


def test_deploy_schema_rejects_unknown_target():
    s = _schema("deploy.schema.json")
    spec = {
        "schema": "deploy/1",
        "product": "demo",
        "components": [{"name": "x", "target": "kubernetes_yolo"}],
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(spec, s)


def test_deploy_schema_rejects_missing_components():
    s = _schema("deploy.schema.json")
    spec = {"schema": "deploy/1", "product": "x", "components": []}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(spec, s)


def test_deploy_schema_accepts_v2():
    """deploy/2 is now a supported schema constant (alongside deploy/1)."""
    s = _schema("deploy.schema.json")
    spec = {"schema": "deploy/2", "product": "x", "components": [{"name": "a", "target": "manual"}]}
    jsonschema.validate(spec, s)


def test_deploy_schema_rejects_unknown_schema_const():
    s = _schema("deploy.schema.json")
    spec = {"schema": "deploy/3", "product": "x", "components": [{"name": "a", "target": "manual"}]}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(spec, s)


# ---- devvault/1 ----


def test_devvault_schema_accepts_minimal():
    s = _schema("devvault.schema.json")
    cat = {"schema": "devvault/1", "product": "demo", "secrets": {"aws": "aws/demo.yml"}}
    jsonschema.validate(cat, s)


def test_devvault_schema_rejects_vault_path_field():
    """vault_path is per-machine, MUST NOT be in the catalog."""
    s = _schema("devvault.schema.json")
    cat = {
        "schema": "devvault/1",
        "product": "demo",
        "secrets": {"aws": "aws/demo.yml"},
        "vault_path": "/wrong/place",
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(cat, s)


def test_devvault_schema_rejects_non_string_paths():
    s = _schema("devvault.schema.json")
    cat = {"schema": "devvault/1", "product": "demo", "secrets": {"aws": 42}}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(cat, s)
