from pathlib import Path

import pytest
import yaml

from wsp import errors
from wsp.manifest import load_manifest


def _write(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "workspace.yml"
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    return p


def test_minimal_manifest(tmp_path):
    p = _write(tmp_path, {"name": "demo", "schema": "awac/1", "stacks": ["core"]})
    m = load_manifest(p)
    assert m.name == "demo"
    assert m.schema == "awac/1"
    assert len(m.stacks) == 1
    assert m.stacks[0].ref == "core"
    assert not m.stacks[0].is_odoo_modules


def test_org_modules_block(tmp_path):
    p = _write(
        tmp_path,
        {
            "name": "x",
            "schema": "awac/1",
            "stacks": ["core", {"org": "erp-partners", "modules": ["mymod"]}],
        },
    )
    m = load_manifest(p)
    assert len(m.stacks) == 2
    assert m.stacks[1].is_odoo_modules
    assert m.stacks[1].odoo_org == "erp-partners"
    assert m.stacks[1].odoo_modules == ["mymod"]


def test_extra_repos(tmp_path):
    p = _write(
        tmp_path,
        {
            "name": "x",
            "schema": "awac/1",
            "stacks": ["core"],
            "extra_repos": [
                {"org": "erp-partners", "repo": "foo", "branch": "19-dev", "path": "addons/foo/"},
            ],
        },
    )
    m = load_manifest(p)
    assert len(m.extra_repos) == 1
    assert m.extra_repos[0].full == "erp-partners/foo"


def test_missing_name_rejected(tmp_path):
    p = _write(tmp_path, {"schema": "awac/1", "stacks": ["core"]})
    with pytest.raises(errors.WspError) as exc:
        load_manifest(p)
    assert exc.value.code == "WSP_002"


def test_unsupported_schema_rejected(tmp_path):
    p = _write(tmp_path, {"name": "x", "schema": "awac/99", "stacks": ["core"]})
    with pytest.raises(errors.WspError) as exc:
        load_manifest(p)
    assert exc.value.code == "WSP_011"


def test_missing_file(tmp_path):
    with pytest.raises(errors.WspError) as exc:
        load_manifest(tmp_path / "nope.yml")
    assert exc.value.code == "WSP_001"
