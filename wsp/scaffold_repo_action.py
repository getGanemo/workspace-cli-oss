"""The high-level `wsp scaffold-repo <full> --category <A|B|C|D|E>` action.

Creates a new product repo (or audits + improves an existing one) so that
its `README.md` matches the convention defined by the governance:

  - Each Cat A/B/C/D repo MUST have a README that answers: ¿qué hace este
    repo? ¿qué stack? ¿quién lo consume? ¿cómo se corre? ¿dónde está el deploy?
  - Cat E (Odoo modules) get a brief README; the canonical metadata lives in
    `__manifest__.py`.

Modes:
  - default        the repo doesn't exist on GitHub yet — create it private
                   with the convention's description, push the README to main.
  - --update       the repo exists. Audit its README against per-category
                   required sections; if it fails, open a PR appending the
                   missing sections with placeholder content.
  - --no-push      generate the seed README locally, print path. No GH calls
                   beyond the existence check.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from wsp import errors


CATEGORIES = ("A", "B", "C", "D", "E")


# ---------- per-category README templates and audit specs ----------


@dataclass
class CategorySpec:
    short_name: str
    required_sections: tuple[str, ...]
    recommended_sections: tuple[str, ...]
    template_fn: "callable"


def _tpl_a(full: str, product: str, repo: str) -> str:
    body = f"""# {full}

`{repo}` of the **{product}** product. Categoría A — gobierno y operaciones.

## Purpose

<One paragraph: what this repo holds and why it is mandatory per Cat A.>

## Structure

<Top-level layout of this repo. For `project_management/` follow the
`manage_project_state` skill. For `agent-stack/` see how `wsp` composes it.
For `infrastructure/` document the Terraform layout per environment.>

## Usage

<How a developer or agent operates on this repo day-to-day.>

## Deployment / Apply

<For `infrastructure/`: Terraform workflow + AWS account + region.
For `agent-stack/` and `project_management/`: 'no deploy' — direct edits + PR.>

## Cross-references

- Governance: <https://github.com/getGanemo/docs-company/blob/main/governance/product-structure.md>
- Product project_management: <https://github.com/{full.split('/')[0]}/project_management>
- AWaC CLI: <https://github.com/getGanemo/workspace-cli>
"""
    return body


def _tpl_b(full: str, product: str, repo: str) -> str:
    return f"""# {full}

`{repo}` of the **{product}** product. Categoría B — superficie pública.

## Purpose

<One paragraph: what this site / docs source publishes and to whom.>

## Public URL

<e.g. https://{product}.com or https://docs.{product}.com>

## Stack

<Frontend framework + hosting. Example: Astro + Tailwind + Cloudflare Pages.>

## Local development

```bash
<install deps>
<dev server>
```

## Build & deployment

<How CI builds and where it deploys.>

## Cross-references

- Governance: <https://github.com/getGanemo/docs-company/blob/main/governance/product-structure.md>
- Product project_management: <https://github.com/{full.split('/')[0]}/project_management>
"""


def _tpl_c(full: str, product: str, repo: str) -> str:
    return f"""# {full}

`{repo}` of the **{product}** product. Categoría C — código de producto.

## Purpose

<One paragraph: what this service / library / app does and why it exists.>

## Stack

<Language, framework, runtime, key libraries.>

## Architecture role

<Where this repo sits in the product architecture. What it consumes, what
it serves. Diagram or one-paragraph description.>

## Primary consumers

<Who or what calls this repo's code: other services, frontends, Odoo modules,
external clients. Be explicit — Cat C convention requires it.>

## API / contract

<If this exposes an API: link to OpenAPI / contract / endpoints reference.
If it consumes one: which API and version.>

## Local development

```bash
<install>
<run>
<test>
```

## Tests

<How to run the test suite. Coverage expectations.>

## Deployment

<CI/CD, target environment, infrastructure repo link.>

## Cross-references

- Governance: <https://github.com/getGanemo/docs-company/blob/main/governance/product-structure.md>
- Product project_management: <https://github.com/{full.split('/')[0]}/project_management>
- Infrastructure: <https://github.com/{full.split('/')[0]}/infrastructure>
"""


def _tpl_d(full: str, product: str, repo: str) -> str:
    return f"""# {full}

`{repo}` of the **{product}** product. Categoría D — componente opcional.

## Purpose

<What this optional component is and when it applies.>

## When this exists

<Cat D is only mandatory under specific conditions — document them here.>

## Stack

<Tech stack, runtime.>

## Usage

<How to use this component. For `*-starter` repos: this section becomes the
public-facing 'Quick start' for developers integrating the product.>

## Cross-references

- Governance: <https://github.com/getGanemo/docs-company/blob/main/governance/product-structure.md>
- Product project_management: <https://github.com/{full.split('/')[0]}/project_management>
"""


def _tpl_e(full: str, product: str, repo: str) -> str:
    return f"""# {full}

Odoo module — Categoría E.

## Producer product

This module is part of the **{product}** product (cross-org integration).

## Manifest

Canonical metadata lives in `__manifest__.py` (name, version, dependencies,
license). This README is for human navigation.

## Branch convention

- `<version>-dev` — development (typically `19-dev` today).
- `<version>.0` — stable.

## Install

<Drop into an Odoo addons path; depends on the modules listed in `__manifest__.py`.>

## Cross-references

- Governance — Categoría E: <https://github.com/getGanemo/docs-company/blob/main/governance/product-structure.md>
- Product project_management: <https://github.com/{product}/project_management>
- Producer's agent-stack `awac.yml#repos` declares this module.
"""


CATEGORY_SPECS: dict[str, CategorySpec] = {
    "A": CategorySpec(
        short_name="governance & operations",
        required_sections=("Purpose", "Structure", "Usage", "Cross-references"),
        recommended_sections=("Deployment", "Apply"),
        template_fn=_tpl_a,
    ),
    "B": CategorySpec(
        short_name="public surface",
        required_sections=("Purpose", "Public URL", "Stack", "Local development", "Cross-references"),
        recommended_sections=("Build", "Deployment"),
        template_fn=_tpl_b,
    ),
    "C": CategorySpec(
        short_name="product code",
        required_sections=(
            "Purpose", "Stack", "Architecture role", "Primary consumers",
            "Local development", "Tests", "Deployment", "Cross-references",
        ),
        recommended_sections=("API", "contract"),
        template_fn=_tpl_c,
    ),
    "D": CategorySpec(
        short_name="optional component",
        required_sections=("Purpose", "Stack", "Usage", "Cross-references"),
        recommended_sections=("When this exists",),
        template_fn=_tpl_d,
    ),
    "E": CategorySpec(
        short_name="Odoo module (cross-org)",
        required_sections=("Producer product", "Manifest", "Cross-references"),
        recommended_sections=("Branch convention", "Install"),
        template_fn=_tpl_e,
    ),
}


# ---------- audit ----------


@dataclass
class AuditResult:
    has_readme: bool
    char_count: int
    h2_headings: list[str]
    missing_required: list[str]
    missing_recommended: list[str]
    too_short: bool

    @property
    def passes(self) -> bool:
        return self.has_readme and not self.missing_required and not self.too_short

    def to_dict(self) -> dict[str, Any]:
        return {
            "has_readme": self.has_readme,
            "char_count": self.char_count,
            "h2_headings": self.h2_headings,
            "missing_required": self.missing_required,
            "missing_recommended": self.missing_recommended,
            "too_short": self.too_short,
            "passes": self.passes,
        }


def _h2_headings(text: str) -> list[str]:
    return [m.group(1).strip() for m in re.finditer(r"^##\s+(.+?)\s*$", text, re.MULTILINE)]


def audit_readme(text: str | None, category: str) -> AuditResult:
    spec = CATEGORY_SPECS[category]
    if text is None:
        return AuditResult(
            has_readme=False, char_count=0, h2_headings=[],
            missing_required=list(spec.required_sections),
            missing_recommended=list(spec.recommended_sections),
            too_short=True,
        )
    headings = _h2_headings(text)
    headings_lc = {h.lower() for h in headings}

    def _present(needle: str) -> bool:
        n = needle.lower()
        return any(n == h or n in h for h in headings_lc)

    missing_req = [s for s in spec.required_sections if not _present(s)]
    missing_rec = [s for s in spec.recommended_sections if not _present(s)]
    too_short = len(text.strip()) < 200
    return AuditResult(
        has_readme=True,
        char_count=len(text),
        h2_headings=headings,
        missing_required=missing_req,
        missing_recommended=missing_rec,
        too_short=too_short,
    )


def patch_existing_readme(existing: str, category: str, full: str, product: str, repo: str) -> str | None:
    """Append missing required sections to an existing README. Return new
    content, or None if no patch is needed."""
    audit = audit_readme(existing, category)
    if audit.passes and not audit.missing_recommended:
        return None

    spec = CATEGORY_SPECS[category]
    additions: list[str] = []

    if audit.too_short and existing.strip():
        additions.append(
            "<!-- The original README is short. Sections below were appended by "
            "`wsp scaffold-repo --update` to satisfy the governance convention. -->"
        )

    for section in audit.missing_required + audit.missing_recommended:
        additions.append(f"\n## {section}\n\n<TODO: {category}-category requirement — fill this in.>\n")

    cross_ref_present = any("cross-reference" in h.lower() for h in audit.h2_headings)
    if not cross_ref_present and "Cross-references" not in spec.required_sections:
        # already covered above
        pass

    if not additions:
        return None
    return existing.rstrip() + "\n\n" + "\n".join(additions) + "\n"


# ---------- result + run ----------


@dataclass
class ScaffoldRepoResult:
    full: str
    org: str
    repo: str
    product: str
    category: str
    repo_existed: bool
    seed_dir: str = ""
    audit: AuditResult | None = None
    patched: bool = False
    pushed: bool = False
    push_target: str = ""  # "main" or "branch:<name>"
    pr_url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "full": self.full,
            "org": self.org,
            "repo": self.repo,
            "product": self.product,
            "category": self.category,
            "repo_existed": self.repo_existed,
            "seed_dir": self.seed_dir,
            "audit": self.audit.to_dict() if self.audit else None,
            "patched": self.patched,
            "pushed": self.pushed,
            "push_target": self.push_target,
            "pr_url": self.pr_url,
        }


def _gh(args: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(["gh", *args], capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def _git(cwd: Path, *args: str) -> tuple[int, str, str]:
    proc = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def _gh_repo_exists(full: str) -> bool:
    rc, _o, _e = _gh(["repo", "view", full, "--json", "name"])
    return rc == 0


def _gh_get_readme(full: str) -> str | None:
    rc, out, _ = _gh(["api", f"repos/{full}/readme", "-H", "Accept: application/vnd.github.raw"])
    if rc != 0:
        return None
    return out


def _create_repo(full: str, description: str) -> None:
    rc, _o, err = _gh([
        "repo", "create", full,
        "--private",
        "--description", description,
    ])
    if rc != 0:
        raise errors.WspError(
            code="WSP_018", category="network",
            cause=f"`gh repo create {full}` failed.",
            remediation="Check the org exists and you have admin:org scope.",
            details={"repo": full, "stderr": err[-1000:]},
        )


def _push_seed_new_repo(seed_dir: Path, full: str, branch: str = "main") -> None:
    _git(seed_dir, "init", "-q", "-b", branch)
    _git(seed_dir, "add", "-A")
    rc, _o, err = _git(seed_dir, "commit", "-q", "-m", "Initial scaffold via wsp scaffold-repo")
    if rc != 0:
        raise errors.WspError(
            code="WSP_018", category="filesystem",
            cause=f"git commit failed in {seed_dir}",
            remediation="Inspect the seed_dir manually.",
            details={"stderr": err[-500:]},
        )
    _git(seed_dir, "remote", "add", "origin", f"https://github.com/{full}.git")
    rc, _o, err = _git(seed_dir, "push", "-u", "origin", branch)
    if rc != 0:
        raise errors.WspError(
            code="WSP_018", category="network",
            cause=f"git push to {full}@{branch} failed.",
            remediation="Check `gh auth status`.",
            details={"stderr": err[-1000:]},
        )


def _update_existing_via_pr(
    full: str,
    new_readme_content: str,
    branch: str,
    pr_title: str,
    pr_body: str,
) -> str:
    """Clone <full>, replace README.md with new_readme_content, push branch, open PR."""
    work = Path(tempfile.mkdtemp(prefix="wsp-scaffold-repo-update-"))
    clone_path = work / "repo"
    rc, _o, err = _git(work, "clone", "--quiet", f"https://github.com/{full}.git", str(clone_path))
    if rc != 0:
        raise errors.WspError(
            code="WSP_018", category="network",
            cause=f"git clone {full} failed.",
            remediation="Check repo access.",
            details={"stderr": err[-500:]},
        )
    rc, _o, err = _git(clone_path, "checkout", "-b", branch)
    if rc != 0:
        raise errors.WspError(
            code="WSP_018", category="filesystem",
            cause=f"git checkout -b {branch} failed.",
            remediation="Pick a different --branch name.",
            details={"stderr": err[-500:]},
        )

    target = clone_path / "README.md"
    target.write_text(new_readme_content, encoding="utf-8")

    rc, out, _ = _git(clone_path, "status", "--porcelain")
    if rc != 0 or not out.strip():
        shutil.rmtree(work, ignore_errors=True)
        return ""

    _git(clone_path, "add", "-A")
    rc, _o, err = _git(clone_path, "commit", "-q", "-m", pr_title)
    if rc != 0:
        raise errors.WspError(
            code="WSP_018", category="filesystem",
            cause="git commit failed in PR branch.",
            remediation="See stderr.",
            details={"stderr": err[-500:]},
        )
    rc, _o, err = _git(clone_path, "push", "--quiet", "--set-upstream", "origin", branch)
    if rc != 0:
        raise errors.WspError(
            code="WSP_018", category="network",
            cause=f"git push to {full}@{branch} failed.",
            remediation="Check `gh auth status`.",
            details={"stderr": err[-500:]},
        )

    rc, out, err = _gh([
        "pr", "create",
        "--repo", full,
        "--head", branch,
        "--title", pr_title,
        "--body", pr_body,
    ])
    if rc != 0:
        raise errors.WspError(
            code="WSP_019", category="network",
            cause=f"gh pr create on {full} failed.",
            remediation="Open the PR manually from the pushed branch.",
            details={"stderr": err[-500:]},
        )
    return out.strip().splitlines()[-1] if out.strip() else ""


def _org_to_product(org: str) -> str:
    p = org.lower()
    if p.startswith("get") and len(p) > 3:
        p = p[3:]
    return p


def _governance_description(
    category: str,
    repo: str,
    product: str,
    *,
    aws_account: str | None = None,
    domain: str | None = None,
) -> str:
    """Compose the GitHub repo description per governance description_pattern.

    Cat A repos have specific patterns codified in the canonical doc:
      project_management → "<Producto> — internal project management, ..."
      agent-stack        → "Agent stack for the <Producto> SaaS product. ..."
      infrastructure     → "<Producto> SaaS — Terraform (AWS account <ID> + Cloudflare <domain>)"

    For Cat A `infrastructure`, callers MUST pass aws_account; if domain is
    omitted we substitute "<domain>" as a placeholder (the user should fix
    it post-create).
    """
    p_title = product.capitalize()
    if category == "A":
        if repo == "project_management":
            return f"{p_title} — internal project management, roadmap, phase progress, and session prompts."
        if repo == "agent-stack":
            return f"Agent stack for the {p_title} SaaS product. Rules, skills, and workflows for AI agents."
        if repo == "infrastructure":
            acct = aws_account or "<AWS_ACCOUNT_ID>"
            dom = domain or f"{product}.com"
            return f"{p_title} SaaS — Terraform (AWS account {acct} + Cloudflare {dom})"
    spec = CATEGORY_SPECS[category]
    return f"{category} — {spec.short_name} for {product}."


def run_scaffold_repo(
    full: str,
    category: str,
    *,
    update: bool = False,
    no_push: bool = False,
    branch: str | None = None,
    aws_account: str | None = None,
    domain: str | None = None,
) -> ScaffoldRepoResult:
    if "/" not in full:
        raise errors.WspError(
            code="WSP_020", category="input",
            cause=f"Repo must be specified as <org>/<name>, got {full!r}.",
            remediation="Pass e.g. `acme/orchestrator`.",
        )
    if category not in CATEGORIES:
        raise errors.WspError(
            code="WSP_020", category="input",
            cause=f"Category must be one of {list(CATEGORIES)}, got {category!r}.",
            remediation="Pass --category A|B|C|D|E.",
        )
    org, repo = full.split("/", 1)
    product = _org_to_product(org)
    spec = CATEGORY_SPECS[category]

    result = ScaffoldRepoResult(
        full=full, org=org, repo=repo, product=product, category=category,
        repo_existed=_gh_repo_exists(full),
    )

    seed_dir = Path(tempfile.mkdtemp(prefix=f"wsp-scaffold-repo-{repo}-"))
    seed_readme = spec.template_fn(full, product, repo)
    (seed_dir / "README.md").write_text(seed_readme, encoding="utf-8")
    result.seed_dir = str(seed_dir)

    if no_push:
        # Audit existing if applicable, even in no_push mode.
        if result.repo_existed:
            existing = _gh_get_readme(full)
            result.audit = audit_readme(existing, category)
        return result

    if not result.repo_existed and not update:
        description = _governance_description(category, repo, product,
                                              aws_account=aws_account, domain=domain)
        _create_repo(full, description)
        _push_seed_new_repo(seed_dir, full, branch="main")
        result.pushed = True
        result.push_target = "main"
        result.audit = audit_readme(seed_readme, category)
        return result

    if update:
        if not result.repo_existed:
            description = _governance_description(category, repo, product,
                                                  aws_account=aws_account, domain=domain)
            _create_repo(full, description)
            tmp_init = Path(tempfile.mkdtemp(prefix="wsp-init-main-"))
            (tmp_init / "README.md").write_text(
                f"# {full}\n\nScaffold pending — see open PR.\n",
                encoding="utf-8",
            )
            _push_seed_new_repo(tmp_init, full, branch="main")
            shutil.rmtree(tmp_init, ignore_errors=True)
            result.repo_existed = True

        existing = _gh_get_readme(full)
        result.audit = audit_readme(existing, category)
        if result.audit.passes and not result.audit.missing_recommended:
            return result

        if existing is None or not existing.strip():
            new_content = seed_readme
        else:
            patched = patch_existing_readme(existing, category, full, product, repo)
            new_content = patched or existing

        side_branch = branch or f"awac/readme-audit-{dt.date.today().isoformat()}"
        title = f"wsp scaffold-repo: README audit (Cat {category})"
        body_parts = [
            f"Auto-generated by `wsp scaffold-repo {full} --category {category} --update`.",
            "",
            f"Audit: { 'PASS' if result.audit.passes else 'FAIL' }",
            f"- char_count: {result.audit.char_count}",
            f"- missing_required: {result.audit.missing_required or 'none'}",
            f"- missing_recommended: {result.audit.missing_recommended or 'none'}",
            "",
            "Sections appended at the end carry `<TODO: …>` placeholders. "
            "Replace them with the real content before merging.",
        ]
        result.pr_url = _update_existing_via_pr(full, new_content, side_branch, title, "\n".join(body_parts))
        result.patched = bool(result.pr_url)
        result.pushed = bool(result.pr_url)
        result.push_target = f"branch:{side_branch}"
        return result

    raise errors.WspError(
        code="WSP_021", category="input",
        cause=f"{full} already exists.",
        remediation="Pass --update to audit and patch, or --no-push to inspect the seed only.",
        details={"repo": full},
    )
