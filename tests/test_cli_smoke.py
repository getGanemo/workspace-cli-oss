import json

from click.testing import CliRunner

from wsp import __version__ as WSP_VERSION
from wsp.cli import main


def test_version():
    runner = CliRunner()
    res = runner.invoke(main, ["--version"])
    assert res.exit_code == 0
    assert WSP_VERSION in res.output


def test_agent_manifest_is_json():
    runner = CliRunner()
    res = runner.invoke(main, ["--agent-manifest"])
    assert res.exit_code == 0
    payload = json.loads(res.output)
    assert payload["name"] == "wsp"
    assert any(c["name"] == "bootstrap" for c in payload["commands"])


def test_schema_workspace():
    runner = CliRunner()
    res = runner.invoke(main, ["schema", "workspace"])
    assert res.exit_code == 0
    payload = json.loads(res.output)
    assert payload["title"] == "AWaC workspace.yml"


def test_help_lists_subcommands():
    runner = CliRunner()
    res = runner.invoke(main, ["--help"])
    assert res.exit_code == 0
    for cmd in ("init", "bootstrap", "sync", "status", "scaffold-stack", "scaffold-repo", "deploy", "secrets", "governance", "audit", "templates", "shortcuts", "doctor", "schema"):
        assert cmd in res.output
