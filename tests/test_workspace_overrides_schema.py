"""Tests that awac/2 manifest with overrides loads, and awac/1 + overrides errors."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from wsp import errors
from wsp.manifest import load_manifest


def _write(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "workspace.yml"
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    return p


def test_awac_v2_manifest_with_deploy_and_devvault_overrides_loads(tmp_path):
    p = _write(
        tmp_path,
        {
            "name": "demo",
            "schema": "awac/2",
            "stacks": ["core"],
            "deploy_overrides": {
                "api": {
                    "odoo_sh": {"project": "staging-x"},
                    "skip": False,
                }
            },
            "devvault_overrides": {
                "cloudflare": "providers/cloudflare-staging.yml",
            },
            "product": "demo",
        },
    )
    m = load_manifest(p)
    assert m.schema == "awac/2"
    assert m.product == "demo"
    assert "api" in m.deploy_overrides
    assert m.deploy_overrides["api"]["odoo_sh"]["project"] == "staging-x"
    assert m.devvault_overrides["cloudflare"] == "providers/cloudflare-staging.yml"


def test_awac_v1_with_deploy_overrides_raises_wsp_018(tmp_path):
    p = _write(
        tmp_path,
        {
            "name": "demo",
            "schema": "awac/1",
            "stacks": ["core"],
            "deploy_overrides": {"api": {"odoo_sh": {"project": "x"}}},
        },
    )
    with pytest.raises(errors.WspError) as exc:
        load_manifest(p)
    assert exc.value.code == "WSP_018"
    assert "awac/2" in exc.value.cause


def test_awac_v1_with_devvault_overrides_raises_wsp_018(tmp_path):
    p = _write(
        tmp_path,
        {
            "name": "demo",
            "schema": "awac/1",
            "stacks": ["core"],
            "devvault_overrides": {"x": "x.yml"},
        },
    )
    with pytest.raises(errors.WspError) as exc:
        load_manifest(p)
    assert exc.value.code == "WSP_018"


def test_awac_v1_without_overrides_still_works(tmp_path):
    p = _write(tmp_path, {"name": "demo", "schema": "awac/1", "stacks": ["core"]})
    m = load_manifest(p)
    assert m.schema == "awac/1"
    assert m.deploy_overrides == {}
    assert m.devvault_overrides == {}
    assert m.product is None


def test_bad_deploy_overrides_shape_rejected(tmp_path):
    p = _write(
        tmp_path,
        {
            "name": "demo",
            "schema": "awac/2",
            "stacks": ["core"],
            "deploy_overrides": "not-a-mapping",
        },
    )
    with pytest.raises(errors.WspError) as exc:
        load_manifest(p)
    assert exc.value.code == "WSP_002"
