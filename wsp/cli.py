"""wsp — command-line entry point.

Agent-first conventions:
  - All commands accept --json for structured output.
  - Errors print structured info ({code, category, cause, remediation}) and
    exit non-zero. The same shape is emitted in plaintext mode (one line)
    or JSON mode (object).
  - `wsp --agent-manifest` prints a machine-readable command catalog.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from importlib import resources
from pathlib import Path
from typing import Any

import click
import yaml

for _stream in (sys.stdout, sys.stderr):
    reconfigure = getattr(_stream, "reconfigure", None)
    if reconfigure is not None:
        try:
            reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

from wsp import __schema__ as WSP_SCHEMA
from wsp import __version__ as WSP_VERSION
from wsp import audit_action, bootstrap_action, deploy_action, errors, git_ops, governance, manifest, registry, scaffold_repo_action, scaffold_stack_action, secrets_action, status_action, sync_action

import hashlib


AGENT_MANIFEST = {
    "name": "wsp",
    "version": WSP_VERSION,
    "schema": WSP_SCHEMA,
    "description": "Agent Workspace as Code (AWaC) CLI for Ganemo.",
    "spec": "https://gist.github.com/GanemoCorp/fdc1042067615003e8aa4a8406198a61",
    "json_default": True,
    "commands": [
        {
            "name": "init",
            "summary": "Scaffold a new workspace.yml from a registry template. Product templates require --yes or --interactive.",
            "args": [
                {"name": "name", "required": False, "description": "Required unless --interactive."},
            ],
            "options": [
                {"name": "--template", "default": "blank"},
                {"name": "--target", "default": "<cwd>/<name>"},
                {"name": "--interactive", "type": "flag", "short": "-i"},
                {"name": "--yes", "type": "flag", "short": "-y", "description": "Confirm product templates non-interactively."},
                {"name": "--json", "type": "flag"},
            ],
            "json_keys": ["workspace", "name", "template", "path", "interactive", "confirmed"],
        },
        {
            "name": "bootstrap",
            "summary": "Resolve, clone, and compose. Idempotent.",
            "options": [
                {"name": "--update-locks", "type": "flag"},
                {"name": "--json", "type": "flag"},
            ],
            "json_keys": ["stacks", "repos", "agent_files", "lock"],
        },
        {
            "name": "sync",
            "summary": "Refresh stacks + recompose .agents/. Does not touch product repos.",
            "options": [{"name": "--json", "type": "flag"}],
            "json_keys": ["stacks", "agent_files", "file_count", "lock", "repos_kept"],
        },
        {
            "name": "status",
            "summary": "Diff workspace.lock.yml vs current state. Read-only.",
            "options": [{"name": "--json", "type": "flag"}],
            "json_keys": ["stacks", "repos", "agents_drift", "summary"],
        },
        {
            "name": "governance",
            "summary": "Governance ↔ awac.yml mirror checks. Subcommand: check.",
            "args": [{"name": "subcommand", "required": True, "choices": ["check"]}],
            "options": [{"name": "--json", "type": "flag"}],
            "json_keys": ["aligned", "problems", "awac_repo", "governance_repo"],
        },
        {
            "name": "scaffold-stack",
            "summary": "Introspect a GitHub org and seed <org>/agent-stack from governance. Auto-registers shortcut + template in core registry by default (use --no-register to skip).",
            "args": [{"name": "org", "required": True}],
            "options": [
                {"name": "--update", "type": "flag"},
                {"name": "--no-push", "type": "flag"},
                {"name": "--no-register", "type": "flag"},
                {"name": "--push-direct", "type": "flag"},
                {"name": "--branch", "default": "awac/scaffold-<date>"},
                {"name": "--json", "type": "flag"},
            ],
            "json_keys": ["org", "product", "classified", "odoo_modules", "pushed", "push_target", "pr_url", "registry_updated", "registry_message"],
        },
        {
            "name": "audit",
            "summary": "Audit a product against governance + AWaC convention. Read-only.",
            "args": [{"name": "product", "required": True}],
            "options": [{"name": "--json", "type": "flag"}],
            "json_keys": ["product", "org", "passed", "summary", "checks"],
        },
        {
            "name": "deploy",
            "summary": "Plan a deploy of <product> from <product>/agent-stack/deploy.yml. Validates schema deploy/1 or deploy/2. When run inside a workspace dir, applies workspace.yml#deploy_overrides.",
            "args": [{"name": "product", "required": True}],
            "options": [
                {"name": "--component", "required": False},
                {"name": "--plan", "type": "flag", "default": True},
                {"name": "--no-overrides", "type": "flag", "description": "Ignore workspace deploy_overrides."},
                {"name": "--json", "type": "flag"},
            ],
            "json_keys": ["product", "spec_path", "validated", "overrides_applied", "components", "skipped_components"],
        },
        {
            "name": "secrets",
            "summary": "Per-product devvault inspection. Subcommand: check. When run inside a workspace dir, applies workspace.yml#devvault_overrides.",
            "args": [{"name": "subcommand", "required": True, "choices": ["check"]},
                     {"name": "product", "required": True}],
            "options": [
                {"name": "--no-overrides", "type": "flag", "description": "Ignore workspace devvault_overrides."},
                {"name": "--json", "type": "flag"},
            ],
            "json_keys": ["product", "vault_path", "entries", "summary"],
        },
        {
            "name": "scaffold-repo",
            "summary": "Create a Cat A/B/C/D/E product repo with a convention README, or audit + patch an existing one's README.",
            "args": [{"name": "full", "required": True, "description": "<org>/<repo>"}],
            "options": [
                {"name": "--category", "required": True, "choices": list(scaffold_repo_action.CATEGORIES)},
                {"name": "--update", "type": "flag"},
                {"name": "--no-push", "type": "flag"},
                {"name": "--branch", "default": "awac/readme-audit-<date>"},
                {"name": "--json", "type": "flag"},
            ],
            "json_keys": ["full", "category", "repo_existed", "audit", "patched", "pushed", "push_target", "pr_url"],
        },
        {
            "name": "templates",
            "summary": "List templates available in the registry. With --json, exposes requires_confirmation, composes_stacks, clones_repos, embeds_in_product_flow per template.",
            "options": [{"name": "--json", "type": "flag"}],
            "json_keys": ["templates"],
        },
        {
            "name": "shortcuts",
            "summary": "List stack shortcuts in the registry.",
            "options": [{"name": "--json", "type": "flag"}],
            "json_keys": ["shortcuts"],
        },
        {
            "name": "doctor",
            "summary": "Diagnose the local environment.",
            "options": [{"name": "--json", "type": "flag"}],
            "json_keys": ["checks"],
        },
        {
            "name": "schema",
            "summary": "Print the JSON Schema for workspace, awac, lock, deploy, or devvault.",
            "args": [{"name": "kind", "required": True, "choices": ["workspace", "awac", "lock", "deploy", "devvault"]}],
        },
        {
            "name": "guide",
            "summary": "Print embedded guide text for a topic. Topics: init, onboard-product, deploy, secrets, discover. With no topic, lists topics.",
            "args": [{"name": "topic", "required": False, "choices": ["init", "onboard-product", "deploy", "secrets", "discover"]}],
            "options": [{"name": "--json", "type": "flag"}],
        },
        {
            "name": "migrate-deploy",
            "summary": "Upgrade a product's deploy/1 spec in the cached stack repo to deploy/2. Adds a single-element targets_available list to each component (conservative).",
            "args": [{"name": "product", "required": True}],
            "options": [{"name": "--json", "type": "flag"}],
            "json_keys": ["stack_repo", "patched_path", "cache_path", "component_count", "noop"],
        },
    ],
    "errors": {
        "shape": ["code", "category", "cause", "remediation", "details"],
        "categories": ["input", "env", "network", "filesystem", "schema", "internal"],
    },
}


def _emit(data: dict[str, Any] | list[Any], as_json: bool, exit_code: int = 0) -> None:
    if as_json:
        click.echo(json.dumps(data, indent=2, sort_keys=False))
    else:
        if isinstance(data, dict):
            for k, v in data.items():
                click.echo(f"{k}: {v}")
        else:
            for item in data:
                click.echo(str(item))
    if exit_code != 0:
        sys.exit(exit_code)


def _emit_error(exc: errors.WspError, as_json: bool) -> None:
    if as_json:
        click.echo(json.dumps({"error": exc.to_dict()}, indent=2), err=True)
    else:
        click.echo(f"error: {exc}", err=True)
        if exc.details:
            click.echo(f"  details: {json.dumps(exc.details, sort_keys=True)}", err=True)
    sys.exit(1)


def _print_agent_manifest(ctx: click.Context, _param: click.Parameter, value: bool) -> None:
    if not value or ctx.resilient_parsing:
        return
    click.echo(json.dumps(AGENT_MANIFEST, indent=2))
    ctx.exit()


@click.group(
    context_settings={"help_option_names": ["-h", "--help"]},
    invoke_without_command=True,
)
@click.version_option(WSP_VERSION, "-V", "--version")
@click.option(
    "--agent-manifest",
    is_flag=True,
    is_eager=True,
    expose_value=False,
    callback=_print_agent_manifest,
    help="Print machine-readable command catalog.",
)
@click.option(
    "--no-update-check",
    is_flag=True,
    expose_value=False,
    callback=lambda ctx, _p, v: os.environ.setdefault("WSP_NO_UPDATE_CHECK", "1") if v else None,
    help="Skip the daily check for newer releases (also: WSP_NO_UPDATE_CHECK=1).",
)
@click.pass_context
def main(ctx: click.Context) -> None:
    """wsp — Agent Workspace as Code (AWaC) CLI."""
    # Best-effort daily update check. Never blocks.
    try:
        from wsp import update_check
        update_check.emit_update_warning_if_any(WSP_VERSION)
    except Exception:
        pass

    if ctx.invoked_subcommand is None:
        if not (Path.cwd() / "workspace.yml").exists():
            click.echo("You are in an empty workspace. To get started:")
            click.echo("  wsp guide init                # read the path before acting")
            click.echo("  wsp init --interactive        # interactive setup")
            click.echo("  wsp init <name> --template blank   # quick non-interactive")
            click.echo("")
            click.echo("For agents discovering AWaC for the first time:")
            click.echo("  wsp guide discover")
            click.echo("")
        click.echo(ctx.get_help())
        ctx.exit()


_KEBAB_CASE_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")


def _validate_workspace_name(value: str) -> str:
    if not _KEBAB_CASE_RE.match(value):
        raise click.BadParameter(
            f"{value!r} is not valid: use kebab-case lowercase ASCII, no leading digit "
            "(e.g. 'my-feature')."
        )
    return value


@main.command()
@click.argument("name", required=False, default=None)
@click.option("--template", "template_name", default=None,
              help="Template name (default: blank in non-interactive; ignored if --interactive).")
@click.option("--target", "target_path", default=None, help="Where to scaffold (default: <cwd>/<name>).")
@click.option("--interactive", "-i", "interactive", is_flag=True,
              help="Interactive mode: pick template + workspace name from prompts.")
@click.option("--yes", "-y", "yes", is_flag=True,
              help="Confirm product templates non-interactively.")
@click.option("--json", "as_json", is_flag=True)
def init(name: str | None, template_name: str | None, target_path: str | None,
         interactive: bool, yes: bool, as_json: bool) -> None:
    """Scaffold a new workspace.yml from a registry template."""
    try:
        reg = registry.load_registry()

        if interactive:
            click.echo("available templates:")
            for t in reg.templates:
                click.echo(f"  - {t.name:28s} {t.description}")
            template_name = click.prompt("template name", type=str)
            ws_name = click.prompt("workspace name", type=str, value_proc=_validate_workspace_name)
            template = reg.template(template_name)
            template = registry.enrich_template_metadata(template)
            if template.is_product_template:
                clones = ", ".join(template.clones_repos) or "(none)"
                composes = ", ".join(template.composes_stacks) or "(none)"
                click.echo(
                    f"This will clone {len(template.clones_repos)} repos: {clones}\n"
                    f"and compose stacks: {composes}.\n"
                    f"Embeds workspace in product flow: {template.embeds_in_product_flow or 'n/a'}"
                )
                if not click.confirm("Continue?", default=False):
                    click.echo("aborted.")
                    sys.exit(1)
            name = ws_name
        else:
            if not name:
                raise click.UsageError("Missing argument 'NAME' (or use --interactive).")
            if template_name is None:
                template_name = "blank"

        target = Path(target_path) if target_path else Path.cwd() / name
        target.mkdir(parents=True, exist_ok=True)
        if (target / "workspace.yml").exists():
            raise errors.target_not_empty(str(target))

        template = reg.template(template_name)
        template = registry.enrich_template_metadata(template)

        if template.is_product_template and not (yes or interactive):
            raise errors.product_template_requires_confirmation(
                template=template_name,
                composes_stacks=template.composes_stacks,
                clones_repos=template.clones_repos,
            )

        text = registry.fetch_template_text(reg, template)
        text = text.replace("<CHANGE-ME>", name)
        (target / "workspace.yml").write_text(text, encoding="utf-8")

        _emit(
            {
                "workspace": str(target.resolve() / "workspace.yml"),
                "name": name,
                "template": template_name,
                "path": str(target.resolve()),
                "interactive": interactive,
                "confirmed": bool(yes or interactive),
            },
            as_json,
        )
    except errors.WspError as exc:
        _emit_error(exc, as_json)


@main.command()
@click.option("--update-locks", is_flag=True, help="Force re-resolution and rewrite the lock.")
@click.option("--json", "as_json", is_flag=True)
def bootstrap(update_locks: bool, as_json: bool) -> None:
    """Resolve, clone, and compose the active workspace."""
    try:
        ws_path = manifest.find_workspace_yml(Path.cwd())
        m = manifest.load_manifest(ws_path)
        reg = registry.load_registry()
        result = bootstrap_action.run_bootstrap(Path.cwd(), m, reg)
        if as_json:
            _emit(result.to_dict(), as_json=True)
        else:
            _print_bootstrap_plaintext(result)
    except errors.WspError as exc:
        _emit_error(exc, as_json)


def _print_bootstrap_plaintext(result: "bootstrap_action.BootstrapResult") -> None:
    payload = result.to_dict()
    for k, v in payload.items():
        if k == "stack_metadata":
            continue
        click.echo(f"{k}: {v}")
    if result.stack_metadata:
        click.echo("\nstack metadata materialized:")
        by_product: dict[str, list[str]] = {}
        for entry in result.stack_metadata:
            by_product.setdefault(entry["product"], []).append(
                Path(entry["file"]).name
            )
        for product, files in by_product.items():
            click.echo(f"  [{product}] .stack/{product}/{{{', '.join(files)}}}")
            workspace_root = Path(result.lock_path).parent if result.lock_path else Path.cwd()
            for hint in _stack_metadata_next_steps(workspace_root, product, files):
                click.echo(f"    → {hint}")


def _stack_metadata_next_steps(
    workspace_root: Path, product: str, files: list[str]
) -> list[str]:
    """Suggest concrete next-step commands based on what was materialized."""
    hints: list[str] = []
    if "devvault.yml" in files:
        path = workspace_root / ".stack" / product / "devvault.yml"
        n = 0
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            from wsp import bootstrap_action as _ba

            body = _ba._strip_synced_header(path.read_text(encoding="utf-8"))
            data = yaml.safe_load(body) or {}
            n = len((data.get("secrets") or {}))
        except Exception:
            n = 0
        hints.append(
            f"{n} secrets declared. Validate your local vault: "
            f"`wsp secrets check {product}`"
        )
    if "deploy.yml" in files:
        path = workspace_root / ".stack" / product / "deploy.yml"
        n = 0
        try:
            from wsp import bootstrap_action as _ba

            body = _ba._strip_synced_header(path.read_text(encoding="utf-8"))
            data = yaml.safe_load(body) or {}
            n = len((data.get("components") or []))
        except Exception:
            n = 0
        hints.append(
            f"{n} deploy components declared. Plan a deploy: "
            f"`wsp deploy {product}`"
        )
    return hints


@main.command()
@click.option("--json", "as_json", is_flag=True)
def sync(as_json: bool) -> None:
    """Refresh stacks and recompose `.agents/` without re-cloning product repos."""
    try:
        ws_path = manifest.find_workspace_yml(Path.cwd())
        m = manifest.load_manifest(ws_path)
        reg = registry.load_registry()
        result = sync_action.run_sync(Path.cwd(), m, reg)
        _emit(result.to_dict(), as_json)
    except errors.WspError as exc:
        _emit_error(exc, as_json)


@main.command()
@click.option("--json", "as_json", is_flag=True)
def status(as_json: bool) -> None:
    """Diff workspace.lock.yml vs current state. Read-only."""
    try:
        ws_path = manifest.find_workspace_yml(Path.cwd())
        manifest.load_manifest(ws_path)  # validate that there is a workspace
        result = status_action.run_status(Path.cwd())
        if as_json:
            _emit(result.to_dict(), as_json=True)
        else:
            _print_status_plaintext(result)
    except errors.WspError as exc:
        _emit_error(exc, as_json)


def _print_status_plaintext(result: "status_action.StatusResult") -> None:
    if not result.has_lock:
        click.echo("no workspace.lock.yml — run `wsp bootstrap` first.")
        sys.exit(2)

    click.echo("stacks:")
    if not result.stacks:
        click.echo("  (none)")
    for s in result.stacks:
        d = s.to_dict()
        marker = "ok" if d["in_sync"] else "drift"
        suffix = ""
        if not d["in_sync"]:
            parts = []
            if s.behind:
                parts.append(f"upstream +{s.behind} (you are behind)")
            if s.ahead:
                parts.append(f"local +{s.ahead}")
            if s.lockfile_commit and s.upstream_commit and s.lockfile_commit != s.upstream_commit and not s.behind and not s.ahead:
                parts.append("lockfile != upstream")
            if parts:
                suffix = " — " + ", ".join(parts)
        click.echo(f"  [{marker}] {s.label} ({s.repo}@{s.ref}) lock={(s.lockfile_commit or '?')[:8]}{suffix}")

    click.echo("\nrepos:")
    if not result.repos:
        click.echo("  (none)")
    for r in result.repos:
        d = r.to_dict()
        marker = "ok" if d["matches_lock"] else "drift"
        bits = []
        if not r.exists:
            bits.append("missing")
        elif not r.is_git:
            bits.append("not-a-git-repo")
        else:
            if r.modified:
                bits.append(f"{len(r.modified)} modified")
            if r.head_commit and r.lockfile_commit and r.head_commit != r.lockfile_commit:
                bits.append(f"head={r.head_commit[:8]} lock={r.lockfile_commit[:8]}")
            if r.behind:
                bits.append(f"behind upstream by {r.behind}")
            if r.ahead:
                bits.append(f"ahead upstream by {r.ahead}")
        suffix = " — " + ", ".join(bits) if bits else ""
        click.echo(f"  [{marker}] {r.repo}@{r.ref} -> {r.path}{suffix}")

    click.echo("\nagents drift:")
    if not result.agents_drift:
        click.echo("  (none)")
    for d in result.agents_drift:
        click.echo(f"  [{d.reason}] {d.file}")


@main.group(name="governance")
def governance_grp() -> None:
    """Governance ↔ awac.yml mirror checks (replaces the old CI workflow)."""


@governance_grp.command(name="check")
@click.option("--json", "as_json", is_flag=True)
def governance_check(as_json: bool) -> None:
    """Compare awac.yml#org_scaffold against the governance doc.

    Both the registry repo and getGanemo/docs-company are pulled into the
    local wsp cache via the same git auth wsp uses for everything else.
    Replaces the previous CI workflow approach (no PAT/secret needed).
    """
    try:
        result = governance.run_governance_check()
        if as_json:
            _emit(result.to_dict(), as_json=True, exit_code=0 if result.aligned else 1)
        else:
            if result.aligned:
                click.echo(
                    f"OK — {result.awac_repo}/awac.yml#org_scaffold is aligned with "
                    f"{result.governance_repo}/governance/product-structure.md."
                )
            else:
                click.echo("DIVERGENCE between awac.yml#org_scaffold and governance:")
                for p in result.problems:
                    click.echo(f"  - {p}")
                click.echo(
                    "\nFix: update either side to match. They must move together "
                    "(see § Mantenimiento in product-structure.md)."
                )
                sys.exit(1)
    except errors.WspError as exc:
        _emit_error(exc, as_json)


@main.command(name="scaffold-stack")
@click.argument("org")
@click.option("--update", is_flag=True, help="Refresh an existing <org>/agent-stack via PR instead of pushing direct.")
@click.option("--no-push", "no_push", is_flag=True, help="Generate the seed locally only; print the path.")
@click.option("--branch", default=None, help="Override the side branch name in --update mode (no effect with --push-direct).")
@click.option("--no-register", "no_register", is_flag=True, help="Skip auto-registering shortcut + template in the core registry. Default: register.")
@click.option("--push-direct", "push_direct", is_flag=True, help="With --update: push refresh straight to main instead of opening a PR. Use when you're the owner and the change is additive (e.g. during onboard_new_product).")
@click.option("--json", "as_json", is_flag=True)
def scaffold_stack_cmd(org: str, update: bool, no_push: bool, branch: str | None, no_register: bool, push_direct: bool, as_json: bool) -> None:
    """Introspect a GitHub org and generate <org>/agent-stack from governance."""
    try:
        reg = registry.load_registry()
        result = scaffold_stack_action.run_scaffold_stack(
            org, reg, update=update, no_push=no_push, branch=branch,
            register_in_core=not no_register, push_direct=push_direct,
        )
        if as_json:
            _emit(result.to_dict(), as_json=True)
        else:
            _print_scaffold_plaintext(result)
    except errors.WspError as exc:
        _emit_error(exc, as_json)


def _print_scaffold_plaintext(result) -> None:
    click.echo(f"org: {result.org}")
    click.echo(f"product: {result.product}")
    click.echo(f"seed_dir: {result.seed_dir}")
    click.echo("\nclassified repos:")
    for c in result.classified:
        click.echo(f"  [{c.category:>2}] {c.facts.name}@{c.facts.default_branch}  ({c.reason})")
    if result.odoo_modules:
        click.echo("\nodoo modules (Cat E, in erp-partners):")
        for m in result.odoo_modules:
            click.echo(f"  - {m.name}@{m.branch_default} -> {m.path}")
    click.echo(f"\nrepo existed: {result.repo_existed}")
    if result.pushed:
        click.echo(f"pushed: yes ({result.push_target})")
    else:
        click.echo("pushed: no (use --update or omit --no-push to push)")
    if result.pr_url:
        click.echo(f"PR: {result.pr_url}")
    if result.registry_message:
        marker = "registry: ok" if result.registry_updated else "registry: skipped/no-op"
        click.echo(f"{marker} — {result.registry_message}")


@main.command()
@click.argument("product")
@click.option("--component", "component_name", default=None,
              help="Filter to a single component (by name) instead of all.")
@click.option("--plan", "plan_only", is_flag=True, default=True,
              help="Plan-only mode (default). The CLI never performs the actual deploy — that is done by the deploy_product workflow + per-target topical workflow per the use_deploy_spec rule.")
@click.option("--no-overrides", "no_overrides", is_flag=True,
              help="Ignore workspace.yml#deploy_overrides and show raw stack defaults.")
@click.option("--json", "as_json", is_flag=True)
def deploy(product: str, component_name: str | None, plan_only: bool, no_overrides: bool, as_json: bool) -> None:
    """Plan a deploy of <product>: read + validate <product>/agent-stack/deploy.yml.

    Always plan-only at the CLI level. Actual execution is workflow-driven
    (see `getGanemo/agent-stack-core-oss/workflows/deploy_product.md`).
    """
    try:
        overrides: dict[str, dict[str, Any]] = {}
        skipped: list[str] = []
        if not no_overrides:
            ws_yml = Path.cwd() / "workspace.yml"
            if ws_yml.exists():
                try:
                    m = manifest.load_manifest(ws_yml)
                    overrides = dict(m.deploy_overrides)
                except errors.WspError:
                    overrides = {}
        result = deploy_action.run_deploy_plan(product, component_name, overrides)
        # Compute skipped: components in spec where override.skip is True
        if overrides:
            for cname, cov in overrides.items():
                if cov.get("skip") is True:
                    skipped.append(cname)
        if as_json:
            payload = result.to_dict()
            payload["skipped_components"] = skipped
            _emit(payload, as_json=True)
        else:
            _print_deploy_plan_plaintext(result, skipped=skipped)
    except errors.WspError as exc:
        _emit_error(exc, as_json)


def _print_deploy_plan_plaintext(result, skipped: list[str] | None = None) -> None:
    skipped = skipped or []
    click.echo(f"product: {result.product}")
    click.echo(f"spec: {result.spec_path}")
    click.echo(f"validated: {'yes' if result.validated else 'no'}")
    if result.overrides_applied:
        click.echo("workspace overrides: applied")
    click.echo("\ncomponents:")
    if not result.components and not skipped:
        click.echo("  (none — pass --component to filter, or check the spec)")
    for c in result.components:
        approval = "human-ack" if c.requires_human_approval else "auto"
        suffix = ""
        if c.workspace_override_applied:
            suffix = "  (workspace override applied)"
        click.echo(f"  - {c.name}  [{c.target}]  ({approval}){suffix}")
        if c.workspace_override_applied and c.overridden_fields:
            click.echo(f"      overridden_fields: {', '.join(c.overridden_fields)}")
        if c.repo:
            click.echo(f"      repo: {c.repo}")
        if c.pre_steps:
            click.echo(f"      pre_steps: {', '.join(c.pre_steps)}")
        if c.target_block:
            for k, v in c.target_block.items():
                click.echo(f"      {c.target}.{k}: {v}")
        for promo in c.promote_after_pass:
            tail = f" (require_pass_on={promo['require_pass_on']})" if promo.get("require_pass_on") else ""
            click.echo(f"      promote -> {promo['target_repo']}@{promo['target_branch']}{tail}")
    for sk in skipped:
        click.echo(f"  - {sk}  (skipped per workspace override)")
    click.echo(
        "\nThis is a plan. Actual execution is workflow-driven — invoke "
        "`deploy_product` workflow in any active stack to run it."
    )


@main.command()
@click.argument("product")
@click.option("--json", "as_json", is_flag=True)
def audit(product: str, as_json: bool) -> None:
    """Audit a product against governance + AWaC convention. Read-only.

    Checks Cat A repos exist with right descriptions, agent-stack carries
    awac.yml + devvault.yml + deploy.yml, registry has shortcut + template.
    """
    try:
        result = audit_action.run_audit(product)
        if as_json:
            _emit(result.to_dict(), as_json=True, exit_code=0 if result.passed else 1)
        else:
            click.echo(f"product: {result.product}")
            click.echo(f"org:     {result.org}\n")
            for c in result.checks:
                marker = {"ok": "ok", "warn": "WARN", "fail": "FAIL"}[c.status]
                click.echo(f"  [{marker:>4}] {c.name}")
                if c.info:
                    click.echo(f"          {c.info}")
                if c.status != "ok" and c.remediation:
                    click.echo(f"          → {c.remediation}")
            s = result.status_summary
            click.echo(f"\nsummary: ok={s['ok']}  warn={s['warn']}  fail={s['fail']}  ({'PASS' if result.passed else 'FAIL'})")
            if not result.passed:
                sys.exit(1)
    except errors.WspError as exc:
        _emit_error(exc, as_json)


@main.group()
def secrets() -> None:
    """DevVault-related subcommands."""


@secrets.command(name="check")
@click.argument("product")
@click.option("--no-overrides", "no_overrides", is_flag=True,
              help="Ignore workspace.yml#devvault_overrides and show raw catalog paths.")
@click.option("--json", "as_json", is_flag=True)
def secrets_check(product: str, no_overrides: bool, as_json: bool) -> None:
    """Check that every secret cataloged for <product> resolves on this machine.

    Reads <product>/agent-stack/devvault.yml + ~/.devvault/.config.yml.
    Reports per-entry: exists / readable. Never prints secret values.
    """
    try:
        overrides: dict[str, str] = {}
        if not no_overrides:
            ws_yml = Path.cwd() / "workspace.yml"
            if ws_yml.exists():
                try:
                    m = manifest.load_manifest(ws_yml)
                    overrides = dict(m.devvault_overrides)
                except errors.WspError:
                    overrides = {}
        result = secrets_action.run_secrets_check(product, overrides)
        if as_json:
            _emit(result.to_dict(), as_json=True, exit_code=0 if result.all_present else 1)
        else:
            click.echo(f"product: {result.product}")
            click.echo(f"catalog: {result.catalog_path}")
            click.echo(f"vault: {result.vault_path}\n")
            for e in result.entries:
                marker = "ok" if e.exists and e.readable else ("missing" if not e.exists else "unreadable")
                ovr = "  (workspace override)" if e.workspace_override else ""
                click.echo(f"  [{marker}] {e.logical_name:14s} -> {e.relative_path}{ovr}")
            if not result.all_present:
                click.echo("\nSome secrets are missing or unreadable. See `use_devvault` rule.")
                sys.exit(1)
    except errors.WspError as exc:
        _emit_error(exc, as_json)


@main.command(name="scaffold-repo")
@click.argument("full")
@click.option("--category", required=True, type=click.Choice(list(scaffold_repo_action.CATEGORIES)),
              help="Governance category (A/B/C/D/E) that determines the README template + audit checklist.")
@click.option("--update", is_flag=True, help="Repo exists — audit its README and open a PR with missing sections appended.")
@click.option("--no-push", "no_push", is_flag=True, help="Generate the seed README locally only; print the path.")
@click.option("--branch", default=None, help="Override the side branch name in --update mode.")
@click.option("--aws-account", "aws_account", default=None, help="AWS account ID for Cat A `infrastructure` description (governance pattern).")
@click.option("--domain", default=None, help="Cloudflare domain for Cat A `infrastructure` description.")
@click.option("--json", "as_json", is_flag=True)
def scaffold_repo_cmd(full: str, category: str, update: bool, no_push: bool, branch: str | None,
                      aws_account: str | None, domain: str | None, as_json: bool) -> None:
    """Create or audit/improve a product repo's README following the governance convention."""
    try:
        result = scaffold_repo_action.run_scaffold_repo(
            full, category, update=update, no_push=no_push, branch=branch,
            aws_account=aws_account, domain=domain,
        )
        if as_json:
            _emit(result.to_dict(), as_json=True)
        else:
            _print_scaffold_repo_plaintext(result)
    except errors.WspError as exc:
        _emit_error(exc, as_json)


def _print_scaffold_repo_plaintext(result) -> None:
    click.echo(f"repo: {result.full}  (category {result.category} — {scaffold_repo_action.CATEGORY_SPECS[result.category].short_name})")
    click.echo(f"product: {result.product}")
    click.echo(f"seed_dir: {result.seed_dir}")
    click.echo(f"repo existed: {result.repo_existed}")
    if result.audit:
        click.echo(f"\naudit: {'PASS' if result.audit.passes else 'FAIL'}")
        click.echo(f"  has_readme: {result.audit.has_readme}")
        click.echo(f"  char_count: {result.audit.char_count}")
        click.echo(f"  missing_required: {result.audit.missing_required or '(none)'}")
        click.echo(f"  missing_recommended: {result.audit.missing_recommended or '(none)'}")
    if result.pushed:
        click.echo(f"\npushed: yes ({result.push_target})")
        if result.pr_url:
            click.echo(f"PR: {result.pr_url}")
    else:
        click.echo("\npushed: no")


@main.command()
@click.option("--json", "as_json", is_flag=True)
def templates(as_json: bool) -> None:
    """List templates available in the registry."""
    try:
        reg = registry.load_registry()
        if as_json:
            items = [registry.enrich_template_metadata(t).to_dict() for t in reg.templates]
            _emit({"templates": items}, as_json=True)
        else:
            for t in reg.templates:
                marker = "[product]" if t.is_product_template else "         "
                click.echo(f"{marker} {t.name:28s} {t.description}")
    except errors.WspError as exc:
        _emit_error(exc, as_json)


@main.command()
@click.option("--json", "as_json", is_flag=True)
def shortcuts(as_json: bool) -> None:
    """List stack shortcuts in the registry."""
    try:
        reg = registry.load_registry()
        items = [{"shortcut": k, "target": v} for k, v in sorted(reg.shortcuts.items())]
        if as_json:
            _emit({"shortcuts": items}, as_json=True)
        else:
            for s in items:
                click.echo(f"{s['shortcut']:14s} → {s['target']}")
    except errors.WspError as exc:
        _emit_error(exc, as_json)


@main.command()
@click.option("--json", "as_json", is_flag=True)
def doctor(as_json: bool) -> None:
    """Diagnose the local environment."""
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, info: str = "", remediation: str = "") -> None:
        checks.append({
            "name": name,
            "status": "ok" if ok else "fail",
            "info": info,
            "remediation": remediation,
        })

    add(
        "git_present",
        git_ops.have_tool("git"),
        info=shutil.which("git") or "",
        remediation="Install git from https://git-scm.com/.",
    )
    gh_path = shutil.which("gh")
    add(
        "gh_present",
        gh_path is not None,
        info=gh_path or "",
        remediation="Install GitHub CLI from https://cli.github.com/ for private repo auth.",
    )

    cache_dir = git_ops.cache_root()
    add(
        "cache_dir_writable",
        _is_writable(cache_dir),
        info=str(cache_dir),
        remediation=f"Make {cache_dir} writable, or set WSP_CACHE_DIR.",
    )

    repo_full = os.environ.get("WSP_REGISTRY_REPO", registry.DEFAULT_REGISTRY_REPO)
    branch = os.environ.get("WSP_REGISTRY_BRANCH", registry.DEFAULT_REGISTRY_BRANCH)
    try:
        reg = registry.load_registry()
        add(
            "registry_reachable",
            True,
            info=f"{reg.repo}@{reg.branch} ({len(reg.shortcuts)} shortcuts, {len(reg.templates)} templates)",
        )
    except errors.WspError as exc:
        add("registry_reachable", False, info=f"{repo_full}@{branch}", remediation=exc.remediation)

    devvault_config = Path.home() / ".devvault" / ".config.yml"
    if devvault_config.exists():
        try:
            cfg = yaml.safe_load(devvault_config.read_text(encoding="utf-8")) or {}
            vault_path = Path(cfg.get("vault_path", str(devvault_config.parent)))
            if vault_path.exists() and vault_path.is_dir():
                add("devvault_config", True, info=f"{devvault_config} → vault_path={vault_path}")
            else:
                add(
                    "devvault_config", False,
                    info=f"vault_path={vault_path} does not exist",
                    remediation=f"Edit {devvault_config} to point at a real directory.",
                )
        except yaml.YAMLError as exc:
            add(
                "devvault_config", False,
                info=f"{devvault_config} parse error: {exc}",
                remediation=f"Fix YAML syntax in {devvault_config}.",
            )
    else:
        add(
            "devvault_config", False,
            info=f"{devvault_config} not found",
            remediation=(
                "Create ~/.devvault/.config.yml with `vault_path: <absolute path>`. "
                "See the use_devvault rule in getGanemo/agent-stack-core-oss."
            ),
        )

    try:
        gov = governance.run_governance_check()
        if gov.aligned:
            add(
                "governance_mirror",
                True,
                info=f"awac.yml ↔ {gov.governance_repo}/governance/product-structure.md aligned",
            )
        else:
            first = gov.problems[0] if gov.problems else "divergence detected"
            add(
                "governance_mirror",
                False,
                info=f"{len(gov.problems)} problem(s); first: {first}",
                remediation="Run `wsp governance check` for the full list. Fix awac.yml or the governance doc.",
            )
    except errors.WspError as exc:
        add(
            "governance_mirror",
            False,
            info=exc.cause,
            remediation=exc.remediation,
        )

    _stack_metadata_drift_check(Path.cwd(), add)

    summary_ok = all(c["status"] == "ok" for c in checks)
    payload = {"checks": checks, "ok": summary_ok}
    if as_json:
        _emit(payload, as_json=True, exit_code=0 if summary_ok else 2)
    else:
        for c in checks:
            mark = "ok" if c["status"] == "ok" else "FAIL"
            click.echo(f"[{mark}] {c['name']}: {c['info']}")
            if c["status"] != "ok" and c["remediation"]:
                click.echo(f"       → {c['remediation']}")
        if not summary_ok:
            sys.exit(2)


def _stack_metadata_drift_check(workspace_root: Path, add) -> None:
    """Compare the workspace's .stack/<product>/* hashes against the lock entries."""
    lock_path = workspace_root / "workspace.lock.yml"
    if not lock_path.exists():
        add("stack_metadata_drift", True, info="no workspace in cwd")
        return
    try:
        lock = yaml.safe_load(lock_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        add(
            "stack_metadata_drift",
            False,
            info=f"could not parse {lock_path}: {exc}",
            remediation="Fix YAML in workspace.lock.yml or re-run `wsp bootstrap`.",
        )
        return
    entries = lock.get("stack_metadata") or []
    if not entries:
        add("stack_metadata_drift", True, info="0 stack metadata files in sync with lock")
        return
    drifted: list[str] = []
    for entry in entries:
        rel = entry.get("file")
        expected = entry.get("sha256")
        if not rel or not expected:
            continue
        target = workspace_root / rel
        if not target.exists():
            drifted.append(rel)
            continue
        text = target.read_text(encoding="utf-8")
        body = bootstrap_action._strip_synced_header(text)
        actual = hashlib.sha256(body.encode("utf-8")).hexdigest()
        if actual != expected:
            drifted.append(rel)
    if drifted:
        add(
            "stack_metadata_drift",
            False,
            info=f"{len(drifted)} drifted: {', '.join(drifted)}",
            remediation=(
                "Edit canonical files in the stack repo, push, then 'wsp sync' "
                "here. To intentionally diverge for this workspace, use "
                "workspace.yml#deploy_overrides or #devvault_overrides instead."
            ),
        )
    else:
        add(
            "stack_metadata_drift",
            True,
            info=f"{len(entries)} stack metadata files in sync with lock",
        )


def _is_writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".wsp_write_probe"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


@main.command()
@click.argument("topic", required=False, default=None)
@click.option("--json", "as_json", is_flag=True)
def guide(topic: str | None, as_json: bool) -> None:
    """Print embedded guide text for a topic, or list topics if none given."""
    from wsp.guides import GUIDE_TOPICS
    try:
        if topic is None:
            if as_json:
                _emit({"topics": [{"name": k, "summary": v} for k, v in GUIDE_TOPICS.items()]}, as_json=True)
            else:
                click.echo("available topics:")
                for k, v in GUIDE_TOPICS.items():
                    click.echo(f"  {k:18s} {v}")
                click.echo("\nusage: wsp guide <topic>")
            return
        if topic not in GUIDE_TOPICS:
            raise errors.WspError(
                code="WSP_010",
                category="input",
                cause=f"Unknown guide topic '{topic}'.",
                remediation=f"Use one of: {', '.join(GUIDE_TOPICS.keys())}.",
                details={"topic": topic, "available": list(GUIDE_TOPICS.keys())},
            )
        text = resources.files("wsp.guides").joinpath(f"{topic}.md").read_text(encoding="utf-8")
        click.echo(text)
    except errors.WspError as exc:
        _emit_error(exc, as_json)


@main.command(name="migrate-deploy")
@click.argument("product")
@click.option("--json", "as_json", is_flag=True)
def migrate_deploy_cmd(product: str, as_json: bool) -> None:
    """Upgrade a deploy/1 spec to deploy/2 in the cached stack repo + write a patched copy.

    Adds a single-element `targets_available: [<existing target>]` to each
    component (conservative; user can broaden manually before PR).
    """
    try:
        result = _migrate_deploy(product)
        if as_json:
            _emit(result, as_json=True)
        else:
            click.echo(
                f"migrated: {result['component_count']} components to deploy/2. "
                f"Patched file: {result['patched_path']}. "
                f"Review and PR to {result['stack_repo']}."
            )
    except errors.WspError as exc:
        _emit_error(exc, as_json)


def _migrate_deploy(product: str) -> dict[str, Any]:
    import tempfile

    reg = registry.load_registry()
    if product in reg.shortcuts:
        full = reg.shortcuts[product]
    else:
        full = f"{product}/agent-stack"
    org, repo = full.split("/", 1)
    cache, _gres = git_ops.ensure_repo(org, repo)
    deploy_yml = cache / "deploy.yml"
    if not deploy_yml.exists():
        raise errors.WspError(
            code="WSP_022", category="filesystem",
            cause=f"No deploy.yml at {deploy_yml}.",
            remediation=f"Author one for {product} first.",
        )
    raw = yaml.safe_load(deploy_yml.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise errors.WspError(
            code="WSP_023", category="schema",
            cause=f"deploy.yml is not a mapping.",
            remediation="Fix the file.",
        )
    if raw.get("schema") == "deploy/2":
        return {
            "stack_repo": full,
            "patched_path": str(deploy_yml),
            "component_count": len(raw.get("components") or []),
            "noop": True,
        }
    raw["schema"] = "deploy/2"
    components = raw.get("components") or []
    for c in components:
        if "targets_available" not in c and "target" in c:
            c["targets_available"] = [c["target"]]
    raw["components"] = components
    out = tempfile.NamedTemporaryFile(
        mode="w", suffix=".yml", prefix=f"deploy-{product}-v2-", delete=False, encoding="utf-8"
    )
    out.write(yaml.safe_dump(raw, sort_keys=False))
    out.close()
    deploy_yml.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return {
        "stack_repo": full,
        "patched_path": out.name,
        "cache_path": str(deploy_yml),
        "component_count": len(components),
        "noop": False,
    }


@main.command()
@click.argument("kind", type=click.Choice(["workspace", "awac", "lock", "deploy", "devvault"]))
def schema(kind: str) -> None:
    """Print the JSON Schema for workspace, awac, lock, deploy, or devvault."""
    file_map = {
        "workspace": "workspace.schema.json",
        "awac": "awac.schema.json",
        "lock": "lock.schema.json",
        "deploy": "deploy.schema.json",
        "devvault": "devvault.schema.json",
    }
    fname = file_map[kind]
    text = resources.files("wsp.schemas").joinpath(fname).read_text(encoding="utf-8")
    click.echo(text)


if __name__ == "__main__":
    main()
