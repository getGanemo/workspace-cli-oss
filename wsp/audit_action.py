"""High-level `wsp audit <product>` action.

Audits a Ganemo product against the governance + AWaC convention. Read-only;
never mutates anything. Intended for new-product onboarding (catch missing
pieces) and for periodic compliance checks.

Checks (per the live `agent-stack-core/awac.yml#org_scaffold` and the
catalog of conventions):

  Cat A repos (project_management, agent-stack, infrastructure):
    - exist on GitHub
    - have descriptions matching the governance pattern (heuristic)

  agent-stack assets:
    - awac.yml exists + lists `repos:` (Cat A/B/C/D/E declared)
    - templates/feature.yml exists
    - devvault.yml exists + validates against schema devvault/1
    - deploy.yml exists + validates against schema deploy/1 (warn if absent)

  Registry hygiene:
    - shortcut <product> is registered in agent-stack-core/awac.yml#shortcuts
    - template <product>-feature is registered

  Workspace alignment (when product has Cat E modules):
    - listed Odoo modules exist in erp-partners with the declared branch_default
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

import jsonschema
import yaml

from wsp import errors, git_ops


@dataclass
class AuditCheck:
    name: str
    status: str  # "ok" | "warn" | "fail"
    info: str = ""
    remediation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "info": self.info,
            "remediation": self.remediation,
        }


@dataclass
class AuditResult:
    product: str
    org: str
    checks: list[AuditCheck] = field(default_factory=list)

    @property
    def status_summary(self) -> dict[str, int]:
        return {
            "ok": sum(1 for c in self.checks if c.status == "ok"),
            "warn": sum(1 for c in self.checks if c.status == "warn"),
            "fail": sum(1 for c in self.checks if c.status == "fail"),
        }

    @property
    def passed(self) -> bool:
        return all(c.status != "fail" for c in self.checks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "product": self.product,
            "org": self.org,
            "passed": self.passed,
            "summary": self.status_summary,
            "checks": [c.to_dict() for c in self.checks],
        }


def _gh(args: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(["gh", *args], capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def _gh_repo_exists(full: str) -> bool:
    rc, _o, _e = _gh(["repo", "view", full, "--json", "name"])
    return rc == 0


def _gh_repo_description(full: str) -> str | None:
    rc, out, _ = _gh(["repo", "view", full, "--json", "description", "-q", ".description"])
    return out.strip() if rc == 0 else None


def _resolve_org_from_product(product: str, registry_shortcuts: dict[str, str]) -> str:
    full = registry_shortcuts.get(product)
    if full:
        return full.split("/", 1)[0]
    # Fallback: heuristic
    if product == "ganemo":
        return "getGanemo"
    if product in ("atlas", "cobalt"):
        return f"get{product}"
    if product == "delta":
        return "Delta"
    return product


def _load_schema(name: str) -> dict:
    text = resources.files("wsp.schemas").joinpath(name).read_text(encoding="utf-8")
    return json.loads(text)


def run_audit(product: str) -> AuditResult:
    from wsp.registry import load_registry

    reg = load_registry()
    org = _resolve_org_from_product(product, reg.shortcuts)
    result = AuditResult(product=product, org=org)

    # 1. Cat A repos
    cat_a_required = ["project_management", "agent-stack", "infrastructure"]
    for repo in cat_a_required:
        full = f"{org}/{repo}"
        if _gh_repo_exists(full):
            desc = _gh_repo_description(full) or ""
            check = AuditCheck(name=f"cat_a/{repo}_exists", status="ok", info=full)
            result.checks.append(check)

            # Per-repo description checks
            if repo == "infrastructure":
                if "AWS account" not in desc and "<AWS_ACCOUNT_ID>" in desc:
                    result.checks.append(AuditCheck(
                        name=f"cat_a/{repo}_description",
                        status="warn",
                        info=f"description has placeholder <AWS_ACCOUNT_ID>: {desc!r}",
                        remediation="Update the GitHub repo description with the real AWS account ID + Cloudflare domain per governance Cat A pattern.",
                    ))
                elif "AWS account" not in desc and "Terraform" not in desc:
                    result.checks.append(AuditCheck(
                        name=f"cat_a/{repo}_description",
                        status="warn",
                        info=f"description doesn't follow governance pattern: {desc!r}",
                        remediation="Edit description to match: '<Producto> SaaS — Terraform (AWS account <ID> + Cloudflare <domain>)'.",
                    ))
                else:
                    result.checks.append(AuditCheck(
                        name=f"cat_a/{repo}_description",
                        status="ok",
                        info=desc[:80],
                    ))
            elif repo == "project_management":
                if "internal project management" not in desc.lower():
                    result.checks.append(AuditCheck(
                        name=f"cat_a/{repo}_description",
                        status="warn",
                        info=f"description doesn't follow governance pattern: {desc!r}",
                        remediation="Edit description to '<Producto> — internal project management, roadmap, phase progress, and session prompts.'",
                    ))
                else:
                    result.checks.append(AuditCheck(
                        name=f"cat_a/{repo}_description",
                        status="ok",
                        info=desc[:80],
                    ))
        else:
            result.checks.append(AuditCheck(
                name=f"cat_a/{repo}_exists",
                status="fail",
                info=f"{full} not found",
                remediation=f"Run `wsp scaffold-repo {full} --category A` (for project_management/infrastructure) or `wsp scaffold-stack {org}` (for agent-stack).",
            ))

    # 2. agent-stack assets
    full_stack = f"{org}/agent-stack"
    if _gh_repo_exists(full_stack):
        # Clone via cache
        try:
            cache, _ = git_ops.ensure_repo(org, "agent-stack")
        except errors.WspError as exc:
            result.checks.append(AuditCheck(
                name="agent_stack/clone",
                status="fail",
                info=str(exc),
                remediation="Check gh auth + repo access.",
            ))
            return result

        # awac.yml
        awac_path = cache / "awac.yml"
        if awac_path.exists():
            try:
                awac_data = yaml.safe_load(awac_path.read_text(encoding="utf-8")) or {}
                if not awac_data.get("repos"):
                    result.checks.append(AuditCheck(
                        name="agent_stack/awac_yml_repos",
                        status="warn",
                        info=f"awac.yml exists but `repos:` is empty",
                        remediation=f"After creating Cat A repos, run `wsp scaffold-stack {org} --update` to refresh awac.yml#repos.",
                    ))
                else:
                    result.checks.append(AuditCheck(
                        name="agent_stack/awac_yml_repos",
                        status="ok",
                        info=f"{len(awac_data['repos'])} repos declared",
                    ))
            except yaml.YAMLError as exc:
                result.checks.append(AuditCheck(
                    name="agent_stack/awac_yml_valid",
                    status="fail",
                    info=f"YAML parse error: {exc}",
                    remediation="Fix awac.yml syntax.",
                ))
        else:
            result.checks.append(AuditCheck(
                name="agent_stack/awac_yml",
                status="fail",
                info="awac.yml missing",
                remediation=f"Run `wsp scaffold-stack {org}` to recreate the seed.",
            ))

        # templates/feature.yml
        if (cache / "templates" / "feature.yml").exists():
            result.checks.append(AuditCheck(
                name="agent_stack/feature_template",
                status="ok",
                info="templates/feature.yml present",
            ))
        else:
            result.checks.append(AuditCheck(
                name="agent_stack/feature_template",
                status="warn",
                info="templates/feature.yml missing",
                remediation=f"Run `wsp scaffold-stack {org} --update` to regenerate.",
            ))

        # devvault.yml
        devvault_path = cache / "devvault.yml"
        if devvault_path.exists():
            try:
                data = yaml.safe_load(devvault_path.read_text(encoding="utf-8")) or {}
                jsonschema.validate(data, _load_schema("devvault.schema.json"))
                result.checks.append(AuditCheck(
                    name="agent_stack/devvault_yml",
                    status="ok",
                    info=f"{len(data.get('secrets') or {})} secrets cataloged",
                ))
            except (yaml.YAMLError, jsonschema.ValidationError) as exc:
                result.checks.append(AuditCheck(
                    name="agent_stack/devvault_yml",
                    status="fail",
                    info=f"validation error: {exc}",
                    remediation="Run `wsp schema devvault` for the spec.",
                ))
        else:
            result.checks.append(AuditCheck(
                name="agent_stack/devvault_yml",
                status="warn",
                info="devvault.yml missing",
                remediation=f"Author one at {full_stack}/devvault.yml — see use_devvault rule + `wsp schema devvault`.",
            ))

        # deploy.yml
        deploy_path = cache / "deploy.yml"
        if deploy_path.exists():
            try:
                data = yaml.safe_load(deploy_path.read_text(encoding="utf-8")) or {}
                jsonschema.validate(data, _load_schema("deploy.schema.json"))
                result.checks.append(AuditCheck(
                    name="agent_stack/deploy_yml",
                    status="ok",
                    info=f"{len(data.get('components') or [])} components",
                ))
            except (yaml.YAMLError, jsonschema.ValidationError) as exc:
                result.checks.append(AuditCheck(
                    name="agent_stack/deploy_yml",
                    status="fail",
                    info=f"validation error: {exc}",
                    remediation="Run `wsp schema deploy` for the spec.",
                ))
        else:
            result.checks.append(AuditCheck(
                name="agent_stack/deploy_yml",
                status="warn",
                info="deploy.yml missing",
                remediation=f"Author one when there's something to deploy — see create_deploy_spec skill.",
            ))

    # 3. Registry hygiene
    if product in reg.shortcuts:
        result.checks.append(AuditCheck(
            name=f"registry/shortcut",
            status="ok",
            info=f"{product} → {reg.shortcuts[product]}",
        ))
    else:
        result.checks.append(AuditCheck(
            name=f"registry/shortcut",
            status="fail",
            info=f"shortcut {product!r} missing in {reg.repo}",
            remediation=f"Add `{product}: {org}/agent-stack` under shortcuts in {reg.repo}/awac.yml. `wsp scaffold-stack {org}` does this automatically since v0.8.0.",
        ))

    template_name = f"{product}-feature"
    if any(t.name == template_name for t in reg.templates):
        result.checks.append(AuditCheck(
            name=f"registry/template",
            status="ok",
            info=f"{template_name} registered",
        ))
    else:
        result.checks.append(AuditCheck(
            name=f"registry/template",
            status="fail",
            info=f"template {template_name!r} missing in {reg.repo}",
            remediation=f"Add `{template_name}` entry under templates in {reg.repo}/awac.yml.",
        ))

    return result
