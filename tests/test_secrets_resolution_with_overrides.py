"""Tests for workspace devvault_overrides applied to the resolved entries."""

from __future__ import annotations

from pathlib import Path

import yaml

from wsp import secrets_action


def _seed_stack(cache_root: Path, product: str, devvault: dict) -> Path:
    stack = cache_root / product / "agent-stack"
    stack.mkdir(parents=True, exist_ok=True)
    (stack / "devvault.yml").write_text(yaml.safe_dump(devvault, sort_keys=False), encoding="utf-8")
    return stack


def _seed_vault(home: Path, vault_dirname: str, files: list[str]) -> Path:
    vault = home / vault_dirname
    vault.mkdir(parents=True, exist_ok=True)
    for rel in files:
        p = vault / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("dummy", encoding="utf-8")
    cfg_dir = home / ".devvault"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / ".config.yml").write_text(
        yaml.safe_dump({"vault_path": str(vault)}, sort_keys=False), encoding="utf-8"
    )
    return cfg_dir


def test_devvault_override_changes_resolved_path(tmp_path, monkeypatch):
    catalog = {
        "schema": "devvault/1",
        "product": "demo",
        "secrets": {
            "cloudflare": "providers/cloudflare-prod.yml",
            "aws": "aws/demo.yml",
        },
    }
    stack = _seed_stack(tmp_path / "cache", "demo", catalog)
    _seed_vault(
        tmp_path,
        "vault",
        ["providers/cloudflare-prod.yml", "providers/cloudflare-staging.yml", "aws/demo.yml"],
    )
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path), raising=False)
    monkeypatch.setattr(secrets_action, "_resolve_catalog_path", lambda product: stack / "devvault.yml")

    overrides = {"cloudflare": "providers/cloudflare-staging.yml"}
    result = secrets_action.run_secrets_check("demo", overrides)

    by_name = {e.logical_name: e for e in result.entries}
    assert by_name["cloudflare"].relative_path == "providers/cloudflare-staging.yml"
    assert by_name["cloudflare"].workspace_override is True
    assert by_name["cloudflare"].exists is True
    assert by_name["aws"].workspace_override is False


def test_no_overrides_falls_back_to_catalog(tmp_path, monkeypatch):
    catalog = {
        "schema": "devvault/1",
        "product": "demo",
        "secrets": {"aws": "aws/demo.yml"},
    }
    stack = _seed_stack(tmp_path / "cache", "demo", catalog)
    _seed_vault(tmp_path, "vault", ["aws/demo.yml"])
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path), raising=False)
    monkeypatch.setattr(secrets_action, "_resolve_catalog_path", lambda product: stack / "devvault.yml")

    result = secrets_action.run_secrets_check("demo", None)
    assert result.entries[0].relative_path == "aws/demo.yml"
    assert result.entries[0].workspace_override is False
