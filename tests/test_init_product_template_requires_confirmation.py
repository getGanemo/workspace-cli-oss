"""Tests that `wsp init` refuses product templates without --yes / --interactive."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from wsp import errors, registry
from wsp.cli import main
from wsp.registry import Registry, Template


def _patch_registry_with_product_template(monkeypatch):
    fake_template = Template(
        name="atlas-feature",
        description="A Atlas product feature workspace.",
        path="atlas-org/agent-stack/templates/feature.yml",
    )
    fake_reg = Registry(
        raw={},
        repo="getGanemo/agent-stack-core-oss",
        branch="main",
        local_path=Path("/dev/null"),
        shortcuts={},
        templates=[fake_template],
        agent_context={},
    )
    monkeypatch.setattr("wsp.cli.registry.load_registry", lambda: fake_reg)
    monkeypatch.setattr(
        "wsp.cli.registry.enrich_template_metadata",
        lambda t: Template(
            name=t.name, description=t.description, path=t.path,
            composes_stacks=["atlas"],
            clones_repos=["atlas-org/atlas-api", "atlas-org/atlas-web"],
            embeds_in_product_flow="atlas",
        ),
    )
    monkeypatch.setattr(
        "wsp.cli.registry.fetch_template_text",
        lambda reg, t: "name: <CHANGE-ME>\nschema: awac/2\nstacks: [atlas]\n",
    )
    return fake_reg


def test_init_product_template_without_yes_raises_wsp_020(tmp_path, monkeypatch):
    _patch_registry_with_product_template(monkeypatch)
    monkeypatch.chdir(tmp_path)
    res = CliRunner().invoke(
        main, ["init", "my-feature", "--template", "atlas-feature", "--json"]
    )
    assert res.exit_code != 0
    payload = json.loads(res.output)
    assert payload["error"]["code"] == "WSP_020"
    # The error references composes_stacks/clones_repos
    cause = payload["error"]["cause"]
    assert "atlas-feature" in cause


def test_init_product_template_with_yes_succeeds(tmp_path, monkeypatch):
    _patch_registry_with_product_template(monkeypatch)
    monkeypatch.chdir(tmp_path)
    res = CliRunner().invoke(
        main, ["init", "my-feature", "--template", "atlas-feature", "--yes", "--json"]
    )
    assert res.exit_code == 0
    payload = json.loads(res.output)
    assert payload["confirmed"] is True
    assert (tmp_path / "my-feature" / "workspace.yml").exists()


def test_init_blank_template_no_confirmation_needed(tmp_path, monkeypatch):
    fake_template = Template(
        name="blank",
        description="Blank workspace.",
        path="getGanemo/agent-stack-core-oss/templates/blank.yml",
    )
    fake_reg = Registry(
        raw={}, repo="getGanemo/agent-stack-core-oss", branch="main",
        local_path=Path("/dev/null"), shortcuts={}, templates=[fake_template], agent_context={},
    )
    monkeypatch.setattr("wsp.cli.registry.load_registry", lambda: fake_reg)
    monkeypatch.setattr(
        "wsp.cli.registry.enrich_template_metadata",
        lambda t: t,
    )
    monkeypatch.setattr(
        "wsp.cli.registry.fetch_template_text",
        lambda reg, t: "name: <CHANGE-ME>\nschema: awac/1\nstacks: [core]\n",
    )
    monkeypatch.chdir(tmp_path)
    res = CliRunner().invoke(main, ["init", "x", "--template", "blank", "--json"])
    assert res.exit_code == 0, res.output
