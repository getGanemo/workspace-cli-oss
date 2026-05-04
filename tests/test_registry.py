from pathlib import Path

import pytest

from wsp import errors
from wsp.registry import Registry, StackRef, Template


def _reg(shortcuts):
    return Registry(
        raw={},
        repo="getGanemo/agent-stack-core-oss",
        branch="main",
        local_path=Path("."),
        shortcuts=shortcuts,
        templates=[],
        agent_context={},
    )


def test_resolve_shortcut():
    reg = _reg({"core": "getGanemo/agent-stack-core-oss", "acme": "acme/agent-stack"})
    ref = reg.resolve("core")
    assert isinstance(ref, StackRef)
    assert ref.org == "getGanemo"
    assert ref.repo == "agent-stack-core-oss"
    assert ref.shortcut == "core"


def test_resolve_full_path():
    reg = _reg({"core": "getGanemo/agent-stack-core-oss"})
    ref = reg.resolve("custom-org/custom-repo")
    assert ref.org == "custom-org"
    assert ref.repo == "custom-repo"
    assert ref.shortcut is None


def test_resolve_unknown_shortcut():
    reg = _reg({"core": "getGanemo/agent-stack-core-oss"})
    with pytest.raises(errors.WspError) as exc:
        reg.resolve("definitely-not-there")
    assert exc.value.code == "WSP_003"


def test_template_lookup():
    reg = _reg({})
    reg.templates = [Template(name="blank", description="x", path="g/r/templates/blank.yml")]
    t = reg.template("blank")
    assert t.path.endswith("blank.yml")


def test_template_unknown():
    reg = _reg({})
    reg.templates = [Template(name="blank", description="x", path="g/r/templates/blank.yml")]
    with pytest.raises(errors.WspError) as exc:
        reg.template("nope")
    assert exc.value.code == "WSP_008"
