"""The high-level `wsp scaffold-stack <org>` action.

Introspects a GitHub org via `gh api`, classifies each repo per the
governance categories declared in `agent-stack-core/awac.yml#org_scaffold`,
and generates a seed `<org>/agent-stack/` directory containing:
  - awac.yml         (product + scope + repos: covering Cat A/B/C/D/E)
  - templates/feature.yml
  - README.md

Push modes:
  - default        push the seed to <org>/agent-stack:main
                   (creates the repo if it doesn't exist)
  - --update       push to a side branch and open a PR (safer for orgs
                   where direct pushes to main are not desired)
  - --no-push      just generate to a local temp directory; print path
"""

from __future__ import annotations

import datetime as dt
import fnmatch
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from wsp import errors, git_ops
from wsp.registry import Registry


CATEGORIES = ("A", "B", "C", "D", "E")


@dataclass
class RepoFacts:
    name: str
    description: str
    default_branch: str
    visibility: str  # "PUBLIC"|"PRIVATE"

    @classmethod
    def from_gh(cls, raw: dict[str, Any]) -> "RepoFacts":
        return cls(
            name=raw.get("name", ""),
            description=(raw.get("description") or ""),
            default_branch=((raw.get("defaultBranchRef") or {}).get("name") or "main") or "main",
            visibility=raw.get("visibility", "PRIVATE"),
        )


@dataclass
class ClassifiedRepo:
    facts: RepoFacts
    category: str  # "A"|"B"|"C"|"D"|"unclassified"
    reason: str = ""


@dataclass
class OdooModuleRef:
    name: str
    branch_default: str = "19-dev"
    path: str = ""
    description: str = ""


@dataclass
class ScaffoldResult:
    org: str
    product: str
    seed_dir: str
    classified: list[ClassifiedRepo] = field(default_factory=list)
    odoo_modules: list[OdooModuleRef] = field(default_factory=list)
    excluded_repos: list[str] = field(default_factory=list)
    repo_existed: bool = False
    pushed: bool = False
    push_target: str = ""  # "main" or "branch:<name>"
    pr_url: str = ""
    registry_updated: bool = False
    registry_message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "org": self.org,
            "product": self.product,
            "seed_dir": self.seed_dir,
            "classified": [
                {
                    "name": c.facts.name,
                    "category": c.category,
                    "default_branch": c.facts.default_branch,
                    "visibility": c.facts.visibility,
                    "reason": c.reason,
                }
                for c in self.classified
            ],
            "odoo_modules": [
                {"name": m.name, "branch_default": m.branch_default, "path": m.path}
                for m in self.odoo_modules
            ],
            "excluded": self.excluded_repos,
            "repo_existed": self.repo_existed,
            "pushed": self.pushed,
            "push_target": self.push_target,
            "pr_url": self.pr_url,
            "registry_updated": self.registry_updated,
            "registry_message": self.registry_message,
        }


def _gh(args: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _gh_repo_list(org: str) -> list[RepoFacts]:
    rc, out, err = _gh([
        "repo", "list", org,
        "--json", "name,description,defaultBranchRef,visibility",
        "--limit", "200",
    ])
    if rc != 0:
        raise errors.WspError(
            code="WSP_012",
            category="network",
            cause=f"`gh repo list {org}` failed.",
            remediation="Check `gh auth status` and that the org exists.",
            details={"org": org, "stderr": err[-1000:]},
        )
    try:
        data = json.loads(out or "[]")
    except json.JSONDecodeError as exc:
        raise errors.WspError(
            code="WSP_012",
            category="network",
            cause=f"`gh repo list {org}` returned invalid JSON: {exc}",
            remediation="Re-run `wsp doctor` and check gh CLI version.",
        )
    return [RepoFacts.from_gh(r) for r in data]


def _gh_repo_exists(full: str) -> bool:
    rc, _o, _e = _gh(["repo", "view", full, "--json", "name"])
    return rc == 0


def org_to_product(org: str) -> str:
    """Lowercase, strip leading 'get' prefix used by Ganemo orgs."""
    p = org.lower()
    if p.startswith("get") and len(p) > 3:
        p = p[3:]
    return p


def classify_repos(
    repos: list[RepoFacts],
    org_scaffold: dict[str, Any],
) -> tuple[list[ClassifiedRepo], list[str]]:
    """Bucket repos into Cat A/B/C/D using rules from registry's org_scaffold.

    Returns (classified, excluded_names_present_in_org).
    """
    cat_a = {r.get("name") for r in (org_scaffold.get("category_a_governance") or {}).get("repos") or []}
    cat_b = {r.get("name") for r in (org_scaffold.get("category_b_public_surface") or {}).get("repos") or []}
    cat_d_named = {r.get("name") for r in (org_scaffold.get("category_d_optional") or {}).get("repos") or [] if r.get("name")}
    cat_d_globs = [r.get("glob") for r in (org_scaffold.get("category_d_optional") or {}).get("repos") or [] if r.get("glob")]
    excluded = set(org_scaffold.get("excluded_names") or [])
    forbidden_c = set(((org_scaffold.get("category_c_product_code") or {}).get("naming_rules") or {}).get("forbidden_names") or [])

    classified: list[ClassifiedRepo] = []
    excluded_present: list[str] = []

    for r in sorted(repos, key=lambda x: x.name):
        name = r.name
        if name in excluded:
            excluded_present.append(name)
            # Most "excluded_names" still belong somewhere, but we exclude
            # them from being declared as Cat C product code.
            if name in cat_a:
                classified.append(ClassifiedRepo(facts=r, category="A", reason="governance"))
            elif name in cat_b:
                classified.append(ClassifiedRepo(facts=r, category="B", reason="public surface"))
            else:
                # Genuinely excluded (e.g. .github)
                continue
            continue
        if name in cat_a:
            classified.append(ClassifiedRepo(facts=r, category="A", reason="governance"))
            continue
        if name in cat_b:
            classified.append(ClassifiedRepo(facts=r, category="B", reason="public surface"))
            continue
        if name in cat_d_named:
            classified.append(ClassifiedRepo(facts=r, category="D", reason="optional component"))
            continue
        if any(fnmatch.fnmatch(name, g) for g in cat_d_globs):
            classified.append(ClassifiedRepo(facts=r, category="D", reason="optional component (glob)"))
            continue
        if name in forbidden_c:
            classified.append(ClassifiedRepo(
                facts=r, category="unclassified",
                reason="forbidden Cat C name (rename or move)",
            ))
            continue
        classified.append(ClassifiedRepo(facts=r, category="C", reason="product code"))

    return classified, excluded_present


def discover_odoo_modules(product: str, erp_partners_repos: list[RepoFacts]) -> list[OdooModuleRef]:
    """Heuristic Cat E detection: name prefix or description match.

    Match if (case-insensitive):
      - repo.name starts with `<product>_` or `<product>-`, OR
      - repo.description contains the product name as a token
    """
    out: list[OdooModuleRef] = []
    p_lc = product.lower()
    name_re = re.compile(rf"^{re.escape(p_lc)}[_\-]", re.IGNORECASE)
    desc_re = re.compile(rf"(?:^|[^a-zA-Z0-9]){re.escape(p_lc)}(?:[^a-zA-Z0-9]|$)", re.IGNORECASE)
    seen: set[str] = set()
    for r in erp_partners_repos:
        name_lc = r.name.lower()
        if name_lc in seen:
            continue
        if name_lc in {"agent-stack", ".github"}:
            continue
        match = name_re.match(name_lc) or desc_re.search(r.description or "")
        if not match:
            continue
        seen.add(name_lc)
        branch = r.default_branch if r.default_branch else "19-dev"
        # Prefer 19-dev as branch_default convention even if GH default branch differs.
        if branch in ("main", "master") and "19" not in branch:
            branch = "19-dev"
        out.append(OdooModuleRef(
            name=r.name,
            branch_default=branch,
            path=f"addons/{r.name}/",
            description=r.description,
        ))
    out.sort(key=lambda m: m.name)
    return out


def _render_awac_yml(
    org: str,
    product: str,
    classified: list[ClassifiedRepo],
    odoo_modules: list[OdooModuleRef],
    cat_a_blank: bool,
) -> str:
    cat_a = [c for c in classified if c.category == "A" and c.facts.name != "agent-stack"]
    cat_b = [c for c in classified if c.category == "B"]
    cat_c = [c for c in classified if c.category == "C"]
    cat_d = [c for c in classified if c.category == "D"]
    unclassified = [c for c in classified if c.category == "unclassified"]

    lines: list[str] = []
    lines.append(f"### Agent Workspace as Code — {product.capitalize()} stack")
    lines.append("#")
    lines.append(f"# Standard repos of the {product} product, declared per the")
    lines.append("# governance at:")
    lines.append("#   getGanemo/docs-company/governance/product-structure.md")
    lines.append("#   getGanemo/agent-stack-core-oss/awac.yml#org_scaffold")
    lines.append("#")
    lines.append(
        f"# Re-run `wsp scaffold-stack {org} --update` to refresh from GitHub when"
    )
    lines.append("# new repos appear in the org or matching Odoo modules are added")
    lines.append("# in erp-partners.")
    lines.append("#")
    lines.append("# Owner: Fernando Pastor (GanemoCorp)")
    lines.append("")
    lines.append(f"product: {product}")
    lines.append(f"scope: {product}-saas")
    lines.append("")
    lines.append("repos:")

    if cat_a_blank:
        lines.append("  # Categoría A — gobierno y operaciones (obligatorios siempre).")
        lines.append(
            "  # scaffold inicial; agregar Cat A cuando el producto exista (project_management,"
        )
        lines.append("  # infrastructure). Hoy no hay repos en esta org.")
    else:
        if cat_a:
            lines.append("  # Categoría A — gobierno y operaciones.")
            for c in cat_a:
                lines.append(f"  - name: {c.facts.name}")
                lines.append(f"    branch_default: {c.facts.default_branch}")
        if cat_b:
            lines.append("")
            lines.append("  # Categoría B — superficie pública.")
            for c in cat_b:
                lines.append(f"  - name: {c.facts.name}")
                lines.append(f"    branch_default: {c.facts.default_branch}")
        if cat_c:
            lines.append("")
            lines.append("  # Categoría C — código de producto.")
            for c in cat_c:
                lines.append(f"  - name: {c.facts.name}")
                lines.append(f"    branch_default: {c.facts.default_branch}")
        if cat_d:
            lines.append("")
            lines.append("  # Categoría D — componentes opcionales.")
            for c in cat_d:
                lines.append(f"  - name: {c.facts.name}")
                lines.append(f"    branch_default: {c.facts.default_branch}")

    if odoo_modules:
        lines.append("")
        lines.append("  # Categoría E — Odoo modules in erp-partners (cross-org).")
        lines.append("  # Auto-detected by heuristic (name prefix or description match).")
        for m in odoo_modules:
            lines.append(f"  - name: {m.name}")
            lines.append("    org:  erp-partners")
            lines.append(f'    path: "{m.path}"')
            lines.append(f'    branch_default: "{m.branch_default}"')

    if unclassified:
        lines.append("")
        lines.append("  # Repos that did not classify automatically — review and fix the name")
        lines.append("  # (forbidden Cat C names: code/app/src/main) or move to a category.")
        for c in unclassified:
            lines.append(f"  # - name: {c.facts.name}  # {c.reason}")

    lines.append("")
    return "\n".join(lines)


def _render_feature_yml(product: str, has_odoo: bool) -> str:
    stacks = ["core"]
    # Drop 'aws' from default — products may not all use AWS. Add only the
    # product stack and erp-partners if Cat E modules were detected.
    stacks.append(product)
    if has_odoo:
        stacks.append("erp-partners")
    lines = [
        f"# Workspace template: {product}-feature",
        f"# Feature work on {product.capitalize()}.",
        "#",
        f"# Auto-clones (per {product}/agent-stack awac.yml):",
        "#   <repos declared above>",
        "#",
        f"# Usage: wsp init <name> --template {product}-feature",
        "",
        "name: <CHANGE-ME>",
        "schema: awac/1",
        "",
        "stacks:",
    ]
    for s in stacks:
        lines.append(f"  - {s}")
    lines.append("")
    return "\n".join(lines)


def _render_readme(org: str, product: str) -> str:
    return (
        f"# {product.capitalize()} agent stack\n\n"
        f"Agent capabilities for the **{product}** product.\n\n"
        "## Contents\n\n"
        "- `awac.yml` — product manifest declaring standard repos (Cat A–E per "
        "[governance](https://github.com/getGanemo/docs-company/blob/main/governance/product-structure.md)).\n"
        "- `templates/feature.yml` — starter `workspace.yml` for `wsp init "
        f"--template {product}-feature`.\n"
        "- `.agents/{rules,skills,workflows}/` — composed into product workspaces by `wsp bootstrap` / `wsp sync`.\n\n"
        "## Refresh from GitHub\n\n"
        "```bash\n"
        f"wsp scaffold-stack {org} --update\n"
        "```\n\n"
        "Generated by `wsp scaffold-stack`. See "
        "[getGanemo/workspace-cli-oss](https://github.com/getGanemo/workspace-cli-oss).\n"
    )


def _merge_existing_awac(existing_text: str, new_repos_block_text: str) -> str:
    """Replace only the `repos:` block in an existing awac.yml.

    Preserves leading comments, `product:`, `scope:`, and any trailing keys.
    `new_repos_block_text` is the rendered output starting at `repos:`.
    """
    lines = existing_text.splitlines(keepends=False)
    repos_start = None
    for i, ln in enumerate(lines):
        if ln.strip().startswith("repos:") and not ln.lstrip().startswith("#"):
            repos_start = i
            break
    if repos_start is None:
        return existing_text.rstrip() + "\n\n" + new_repos_block_text + "\n"

    # Find end of the repos block: next top-level key or EOF.
    repos_end = len(lines)
    for j in range(repos_start + 1, len(lines)):
        s = lines[j]
        if not s:
            continue
        if not s.startswith(" ") and not s.startswith("#") and not s.startswith("\t"):
            repos_end = j
            break

    # The new block we render starts at "repos:" — find that anchor.
    new_lines = new_repos_block_text.splitlines()
    new_repos_start = next((i for i, ln in enumerate(new_lines) if ln.strip().startswith("repos:")), 0)
    new_repos_block = new_lines[new_repos_start:]

    head = lines[:repos_start]
    tail = lines[repos_end:]
    out = head + new_repos_block + [""] + tail
    return "\n".join(out).rstrip() + "\n"


def write_seed(
    seed_dir: Path,
    org: str,
    product: str,
    classified: list[ClassifiedRepo],
    odoo_modules: list[OdooModuleRef],
    cat_a_blank: bool,
) -> None:
    seed_dir.mkdir(parents=True, exist_ok=True)
    (seed_dir / "awac.yml").write_text(
        _render_awac_yml(org, product, classified, odoo_modules, cat_a_blank),
        encoding="utf-8",
    )
    templates_dir = seed_dir / "templates"
    templates_dir.mkdir(exist_ok=True)
    (templates_dir / "feature.yml").write_text(
        _render_feature_yml(product, has_odoo=bool(odoo_modules)),
        encoding="utf-8",
    )
    (seed_dir / "README.md").write_text(_render_readme(org, product), encoding="utf-8")
    # Empty .agents/ so the layout matches sibling stacks.
    for sub in ("rules", "skills", "workflows"):
        (seed_dir / sub).mkdir(exist_ok=True)
        gitkeep = seed_dir / sub / ".gitkeep"
        if not any((seed_dir / sub).iterdir()):
            gitkeep.write_text("", encoding="utf-8")


def _git(cwd: Path, *args: str) -> tuple[int, str, str]:
    proc = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def _create_repo(full: str, description: str) -> None:
    rc, _o, err = _gh([
        "repo", "create", full,
        "--private",
        "--description", description,
    ])
    if rc != 0:
        raise errors.WspError(
            code="WSP_013",
            category="network",
            cause=f"`gh repo create {full}` failed.",
            remediation="Check that the org exists and you have admin:org scope.",
            details={"repo": full, "stderr": err[-1000:]},
        )


def _push_seed_new_repo(seed_dir: Path, full: str, branch: str = "main") -> None:
    """Initialize seed_dir as a git repo and push to origin/<branch>."""
    _git(seed_dir, "init", "-q", "-b", branch)
    _git(seed_dir, "add", "-A")
    rc, _o, err = _git(seed_dir, "commit", "-q", "-m", "Initial scaffold via wsp scaffold-stack")
    if rc != 0:
        raise errors.WspError(
            code="WSP_014", category="filesystem",
            cause=f"git commit failed in {seed_dir}",
            remediation="Inspect the seed_dir manually.",
            details={"stderr": err[-500:]},
        )
    _git(seed_dir, "remote", "add", "origin", f"https://github.com/{full}.git")
    rc, _o, err = _git(seed_dir, "push", "-u", "origin", branch)
    if rc != 0:
        raise errors.WspError(
            code="WSP_014", category="network",
            cause=f"git push to {full}@{branch} failed.",
            remediation="Check `gh auth status` and the credential helper.",
            details={"stderr": err[-1000:]},
        )


def _update_existing_repo_via_pr(
    full: str,
    seed_dir: Path,
    branch: str,
    pr_title: str,
    pr_body: str,
) -> str:
    """Clone <full>, merge seed into it, push branch, open PR. Returns PR URL."""
    work = Path(tempfile.mkdtemp(prefix="wsp-scaffold-update-"))
    clone_path = work / "repo"
    rc, _o, err = _git(work, "clone", "--quiet", f"https://github.com/{full}.git", str(clone_path))
    if rc != 0:
        raise errors.WspError(
            code="WSP_014", category="network",
            cause=f"git clone {full} failed.",
            remediation="Check repo access.",
            details={"stderr": err[-500:]},
        )
    rc, _o, err = _git(clone_path, "checkout", "-b", branch)
    if rc != 0:
        raise errors.WspError(
            code="WSP_014", category="filesystem",
            cause=f"git checkout -b {branch} failed.",
            remediation="Pick a different --branch name.",
            details={"stderr": err[-500:]},
        )

    # Merge seed:
    # - awac.yml: if exists, replace only the repos: block; else copy.
    new_awac = (seed_dir / "awac.yml").read_text(encoding="utf-8")
    target_awac = clone_path / "awac.yml"
    if target_awac.exists():
        merged = _merge_existing_awac(target_awac.read_text(encoding="utf-8"), new_awac)
        target_awac.write_text(merged, encoding="utf-8")
    else:
        target_awac.write_text(new_awac, encoding="utf-8")

    # templates/feature.yml: only write if missing.
    feat = clone_path / "templates" / "feature.yml"
    if not feat.exists():
        feat.parent.mkdir(parents=True, exist_ok=True)
        feat.write_text((seed_dir / "templates" / "feature.yml").read_text(encoding="utf-8"), encoding="utf-8")

    # README.md: only write if missing.
    readme = clone_path / "README.md"
    if not readme.exists():
        readme.write_text((seed_dir / "README.md").read_text(encoding="utf-8"), encoding="utf-8")

    rc, out, _ = _git(clone_path, "status", "--porcelain")
    if rc != 0 or not out.strip():
        # Nothing changed — clean up and report a no-op
        shutil.rmtree(work, ignore_errors=True)
        return ""

    _git(clone_path, "add", "-A")
    rc, _o, err = _git(clone_path, "commit", "-q", "-m", pr_title)
    if rc != 0:
        raise errors.WspError(
            code="WSP_014", category="filesystem",
            cause="git commit failed in PR branch.",
            remediation="See stderr.",
            details={"stderr": err[-500:]},
        )
    rc, _o, err = _git(clone_path, "push", "--quiet", "--set-upstream", "origin", branch)
    if rc != 0:
        raise errors.WspError(
            code="WSP_014", category="network",
            cause=f"git push to {full}@{branch} failed.",
            remediation="Check `gh auth status`.",
            details={"stderr": err[-500:]},
        )

    # Open the PR.
    rc, out, err = _gh([
        "pr", "create",
        "--repo", full,
        "--head", branch,
        "--title", pr_title,
        "--body", pr_body,
    ])
    if rc != 0:
        raise errors.WspError(
            code="WSP_015", category="network",
            cause=f"gh pr create on {full} failed.",
            remediation="Open the PR manually from the pushed branch.",
            details={"stderr": err[-500:]},
        )
    pr_url = out.strip().splitlines()[-1] if out.strip() else ""
    return pr_url


def _update_existing_repo_via_direct_push(
    full: str,
    seed_dir: Path,
    commit_msg: str,
) -> bool:
    """Clone <full>, merge seed into it, push to main directly. Returns True
    if anything was pushed, False if no changes were needed (no-op).

    Used when --push-direct is set on `scaffold-stack --update`. Caller is
    expected to be the owner (push will fail otherwise) and to know that
    the change is safe to merge without review (additive `repos:` updates,
    optional README/feature.yml seeds).
    """
    work = Path(tempfile.mkdtemp(prefix="wsp-scaffold-direct-"))
    clone_path = work / "repo"
    rc, _o, err = _git(work, "clone", "--quiet", f"https://github.com/{full}.git", str(clone_path))
    if rc != 0:
        raise errors.WspError(
            code="WSP_014", category="network",
            cause=f"git clone {full} failed.",
            remediation="Check repo access.",
            details={"stderr": err[-500:]},
        )

    # Merge seed (same logic as PR mode):
    new_awac = (seed_dir / "awac.yml").read_text(encoding="utf-8")
    target_awac = clone_path / "awac.yml"
    if target_awac.exists():
        merged = _merge_existing_awac(target_awac.read_text(encoding="utf-8"), new_awac)
        target_awac.write_text(merged, encoding="utf-8")
    else:
        target_awac.write_text(new_awac, encoding="utf-8")

    feat = clone_path / "templates" / "feature.yml"
    if not feat.exists():
        feat.parent.mkdir(parents=True, exist_ok=True)
        feat.write_text((seed_dir / "templates" / "feature.yml").read_text(encoding="utf-8"), encoding="utf-8")

    readme = clone_path / "README.md"
    if not readme.exists():
        readme.write_text((seed_dir / "README.md").read_text(encoding="utf-8"), encoding="utf-8")

    rc, out, _ = _git(clone_path, "status", "--porcelain")
    if rc != 0 or not out.strip():
        shutil.rmtree(work, ignore_errors=True)
        return False

    _git(clone_path, "add", "-A")
    rc, _o, err = _git(clone_path, "commit", "-q", "-m", commit_msg)
    if rc != 0:
        raise errors.WspError(
            code="WSP_014", category="filesystem",
            cause="git commit failed in --push-direct update.",
            remediation="See stderr.",
            details={"stderr": err[-500:]},
        )
    rc, _o, err = _git(clone_path, "push", "--quiet", "origin", "HEAD:main")
    if rc != 0:
        raise errors.WspError(
            code="WSP_014", category="network",
            cause=f"git push --push-direct to {full}@main failed. You may not have direct push permission — fall back to --update without --push-direct (PR mode).",
            remediation="Drop --push-direct or use --branch <name> to open a PR instead.",
            details={"stderr": err[-500:]},
        )
    shutil.rmtree(work, ignore_errors=True)
    return True


def _register_in_core_registry(
    registry: Registry,
    product: str,
    org: str,
) -> tuple[bool, str]:
    """Add `<product>: <org>/agent-stack` shortcut + `<product>-feature` template
    to the core registry (`agent-stack-core/awac.yml`). Push direct to main.

    Returns (changed, message). If already registered, no-op (changed=False).
    """
    cache = registry.local_path
    awac_path = cache / "awac.yml"
    if not awac_path.exists():
        return (False, "registry awac.yml not found")

    text = awac_path.read_text(encoding="utf-8")
    shortcut_line = f"  {product}:".ljust(15) + f" {org}/agent-stack"
    template_block = (
        f"  - name: {product}-feature\n"
        f'    description: "Feature en {product.capitalize()}."\n'
        f"    path: {org}/agent-stack/templates/feature.yml\n"
    )

    needs_shortcut = re.search(rf"^\s*{re.escape(product)}\s*:\s*{re.escape(org)}/agent-stack",
                               text, re.MULTILINE) is None
    needs_template = f"name: {product}-feature" not in text

    if not needs_shortcut and not needs_template:
        return (False, f"{product} already registered in core")

    new_text = text

    if needs_shortcut:
        # Insert before the lazy-products comment line, or at end of shortcuts block
        m = re.search(r"^shortcuts:\n", new_text, re.MULTILINE)
        if not m:
            return (False, "shortcuts: anchor not found in registry")
        # Find end of shortcuts block (next top-level key, e.g. "templates:" or "org_scaffold:")
        rest = new_text[m.end():]
        end_match = re.search(r"\n[a-z_]+:\s*\n", rest)
        end_pos = m.end() + end_match.start() if end_match else len(new_text)
        # Insert shortcut just before that boundary, on its own line
        insertion = f"  {product}:".ljust(15) + f" {org}/agent-stack\n"
        new_text = new_text[:end_pos] + insertion + new_text[end_pos:]

    if needs_template:
        # Find templates: block end (next top-level key)
        m = re.search(r"^templates:\n", new_text, re.MULTILINE)
        if not m:
            return (False, "templates: anchor not found in registry")
        rest = new_text[m.end():]
        end_match = re.search(r"\n[a-z_]+:\s*\n", rest)
        end_pos = m.end() + end_match.start() if end_match else len(new_text)
        # Strip trailing blank line at end_pos so the new entry tucks neatly
        new_text = new_text[:end_pos].rstrip() + "\n\n" + template_block + new_text[end_pos:]

    awac_path.write_text(new_text, encoding="utf-8")

    # Commit + push direct to main (additive change, low-risk).
    org_core, repo_core = registry.repo.split("/", 1)
    rc, _o, err = _git(cache, "add", "awac.yml")
    if rc != 0:
        return (False, f"git add failed: {err[-200:]}")
    rc, _o, err = _git(cache, "commit", "-q", "-m",
                       f"Register {product} stack: shortcut + {product}-feature template")
    if rc != 0:
        return (False, f"git commit failed: {err[-200:]}")
    rc, _o, err = _git(cache, "push", "--quiet", "origin", "HEAD:main")
    if rc != 0:
        return (False, f"git push failed: {err[-200:]}")

    return (True, f"{product} registered in {registry.repo}")


def run_scaffold_stack(
    org: str,
    registry: Registry,
    *,
    update: bool = False,
    no_push: bool = False,
    branch: str | None = None,
    register_in_core: bool = True,
    push_direct: bool = False,
) -> ScaffoldResult:
    org_scaffold = registry.raw.get("org_scaffold") or {}
    if not org_scaffold:
        raise errors.WspError(
            code="WSP_005", category="schema",
            cause="Registry has no org_scaffold block.",
            remediation="Update the registry repo (agent-stack-core/awac.yml).",
        )

    product = org_to_product(org)
    repos = _gh_repo_list(org)
    classified, _excluded = classify_repos(repos, org_scaffold)
    cat_a_blank = not any(c.category == "A" for c in classified)

    odoo_modules: list[OdooModuleRef] = []
    if (org_scaffold.get("category_e_cross_org") or {}).get("odoo_modules"):
        erp_partners_repos = _gh_repo_list("erp-partners")
        odoo_modules = discover_odoo_modules(product, erp_partners_repos)

    seed_dir = Path(tempfile.mkdtemp(prefix=f"wsp-scaffold-{product}-"))
    write_seed(seed_dir, org, product, classified, odoo_modules, cat_a_blank=cat_a_blank)

    result = ScaffoldResult(
        org=org,
        product=product,
        seed_dir=str(seed_dir),
        classified=classified,
        odoo_modules=odoo_modules,
        excluded_repos=_excluded,
    )

    full = f"{org}/agent-stack"
    result.repo_existed = _gh_repo_exists(full)

    if no_push:
        return result

    if not result.repo_existed and not update:
        # Brand new repo, default direct push.
        description = f"Agent stack for the {product.capitalize()} SaaS product."
        _create_repo(full, description)
        _push_seed_new_repo(seed_dir, full, branch="main")
        result.pushed = True
        result.push_target = "main"
        if register_in_core:
            ok, msg = _register_in_core_registry(registry, product, org)
            result.registry_updated = ok
            result.registry_message = msg
        return result

    if update:
        if not result.repo_existed:
            # Need to bootstrap an empty main first so PRs can target it.
            description = f"Agent stack for the {product.capitalize()} SaaS product."
            _create_repo(full, description)
            tmp_init = Path(tempfile.mkdtemp(prefix="wsp-init-main-"))
            (tmp_init / "README.md").write_text(
                f"# {product.capitalize()} agent stack\n\nScaffold pending — see open PR.\n",
                encoding="utf-8",
            )
            _push_seed_new_repo(tmp_init, full, branch="main")
            shutil.rmtree(tmp_init, ignore_errors=True)
            result.repo_existed = True

        if push_direct:
            commit_msg = f"wsp scaffold-stack --update: refresh awac.yml#repos for {org}"
            changed = _update_existing_repo_via_direct_push(full, seed_dir, commit_msg)
            result.pushed = changed
            result.push_target = "main" if changed else "main (no-op — already current)"
            result.pr_url = ""
        else:
            side_branch = branch or f"awac/scaffold-{dt.date.today().isoformat()}"
            title = "wsp scaffold-stack: refresh awac.yml + seed"
            body = (
                "Auto-generated by `wsp scaffold-stack` from the live state of\n"
                f"the **{org}** GitHub org.\n\n"
                "Replaces only the `repos:` block in `awac.yml`. Adds "
                "`templates/feature.yml` and `README.md` if they don't exist.\n\n"
                "Review the classification below before merging.\n"
            )
            result.pr_url = _update_existing_repo_via_pr(full, seed_dir, side_branch, title, body)
            result.pushed = bool(result.pr_url)
            result.push_target = f"branch:{side_branch}"
        if register_in_core:
            ok, msg = _register_in_core_registry(registry, product, org)
            result.registry_updated = ok
            result.registry_message = msg
        return result

    # repo_existed AND not update → refuse
    raise errors.WspError(
        code="WSP_016", category="input",
        cause=f"{full} already exists.",
        remediation="Pass --update to refresh it via PR, or --no-push to inspect the seed only.",
        details={"repo": full},
    )
