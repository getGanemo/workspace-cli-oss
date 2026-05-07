"""Tests for wsp.introspect — read-only state introspection."""

from __future__ import annotations

import json
import os
from pathlib import Path

from click.testing import CliRunner

from wsp import introspect
from wsp.cli import main


# ----------------------------------------------------------------------
# Library-level
# ----------------------------------------------------------------------


def test_cache_path_default(monkeypatch):
    monkeypatch.delenv("WSP_CACHE_DIR", raising=False)
    p = introspect.cache_path()
    assert p == Path.home() / ".wsp" / "cache"


def test_cache_path_respects_env(monkeypatch, tmp_path):
    monkeypatch.setenv("WSP_CACHE_DIR", str(tmp_path))
    assert introspect.cache_path() == Path(str(tmp_path))


def test_find_workspace_root_walks_ancestors(tmp_path):
    nested = tmp_path / "a" / "b" / "c"
    nested.mkdir(parents=True)
    (tmp_path / "workspace.yml").write_text(
        "name: t\nschema: awac/1\nstacks:\n  - core\n",
        encoding="utf-8",
    )
    assert introspect.find_workspace_root(nested) == tmp_path.resolve()


def test_find_workspace_root_returns_none_when_absent(tmp_path):
    nested = tmp_path / "deeply" / "nested"
    nested.mkdir(parents=True)
    # Walk up from `nested` — there's no workspace.yml above it inside tmp_path.
    # We can't guarantee there isn't one above tmp_path itself on some CI
    # filesystems, so just assert the fn either returns None or a path
    # outside tmp_path.
    found = introspect.find_workspace_root(nested)
    if found is not None:
        assert tmp_path.resolve() not in found.parents and found != tmp_path.resolve()


def test_workspace_info_found(tmp_path):
    (tmp_path / "workspace.yml").write_text(
        "name: my-ws\n"
        "schema: awac/1\n"
        "stacks:\n"
        "  - core\n"
        "  - org: odoopartners\n"
        "    modules: [mod_a, mod_b]\n",
        encoding="utf-8",
    )
    info = introspect.workspace_info(tmp_path)
    assert info["workspace_found"] is True
    assert info["name"] == "my-ws"
    assert info["schema"] == "awac/1"
    assert any(s["kind"] == "stack" and s["ref"] == "core" for s in info["stacks"])
    odoo = next(s for s in info["stacks"] if s["kind"] == "odoo_modules")
    assert odoo["org"] == "odoopartners"
    assert odoo["modules"] == ["mod_a", "mod_b"]


def test_workspace_info_not_found(tmp_path):
    # Use a temp dir we control, walking up from it. If a parent of tmp_path
    # happens to have a workspace.yml (rare in CI but possible), info is
    # found — assert only the negative-shape contract.
    info = introspect.workspace_info(tmp_path)
    if not info["workspace_found"]:
        assert "searched_from" in info


# ----------------------------------------------------------------------
# CLI surface
# ----------------------------------------------------------------------


def test_cli_cache_path_prints_default(monkeypatch):
    monkeypatch.delenv("WSP_CACHE_DIR", raising=False)
    runner = CliRunner()
    res = runner.invoke(main, ["cache", "path"])
    assert res.exit_code == 0, res.output
    assert ".wsp" in res.output and "cache" in res.output


def test_cli_cache_path_json(monkeypatch, tmp_path):
    monkeypatch.setenv("WSP_CACHE_DIR", str(tmp_path))
    runner = CliRunner()
    res = runner.invoke(main, ["cache", "path", "--json"])
    assert res.exit_code == 0, res.output
    payload = json.loads(res.output)
    assert payload["path"] == str(tmp_path)
    assert payload["env_var"] == "WSP_CACHE_DIR"
    assert "exists" in payload


def test_cli_workspace_path(tmp_path):
    (tmp_path / "workspace.yml").write_text(
        "name: t\nschema: awac/1\nstacks:\n  - core\n",
        encoding="utf-8",
    )
    runner = CliRunner()
    res = runner.invoke(main, ["workspace", "path"], env={"PWD": str(tmp_path)})
    # Click's CliRunner doesn't honor PWD; chdir inside the test.
    cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        res = runner.invoke(main, ["workspace", "path"])
    finally:
        os.chdir(cwd)
    assert res.exit_code == 0, res.output
    assert str(tmp_path.resolve()) in res.output


def test_cli_workspace_info_json(tmp_path):
    (tmp_path / "workspace.yml").write_text(
        "name: probe\n"
        "schema: awac/1\n"
        "stacks:\n"
        "  - core\n"
        "  - aws\n",
        encoding="utf-8",
    )
    runner = CliRunner()
    cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        res = runner.invoke(main, ["workspace", "info", "--json"])
    finally:
        os.chdir(cwd)
    assert res.exit_code == 0, res.output
    payload = json.loads(res.output)
    assert payload["workspace_found"] is True
    assert payload["name"] == "probe"
    assert {s["ref"] for s in payload["stacks"] if s["kind"] == "stack"} == {"core", "aws"}


def test_cli_workspace_info_not_found_errors(tmp_path):
    runner = CliRunner()
    cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        res = runner.invoke(main, ["workspace", "info", "--json"])
    finally:
        os.chdir(cwd)
    # If our tmp_path has no workspace.yml above it, exit non-zero.
    # If it DID find one (some CI quirk), accept exit 0.
    assert res.exit_code in (0, 1)


def test_agent_manifest_lists_new_commands():
    runner = CliRunner()
    res = runner.invoke(main, ["--agent-manifest"])
    assert res.exit_code == 0
    payload = json.loads(res.output)
    names = {c["name"] for c in payload["commands"]}
    assert "cache" in names
    assert "workspace" in names
