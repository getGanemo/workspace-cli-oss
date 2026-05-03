"""Governance ↔ awac.yml mirror check, executed locally by the CLI.

Replaces the previous GitHub Actions workflow approach. The CLI already has
`gh` authenticated, so it can clone `getGanemo/docs-company` on-demand
without any PAT or workflow secret.

Public surface:
  - run_governance_check() -> CheckResult — used by `wsp governance check`
    and `wsp doctor`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from wsp import errors, git_ops


DEFAULT_GOVERNANCE_REPO = "getGanemo/docs-company"
DEFAULT_GOVERNANCE_BRANCH = "main"
DEFAULT_GOVERNANCE_DOC_PATH = "governance/product-structure.md"


@dataclass
class CheckResult:
    aligned: bool
    problems: list[str] = field(default_factory=list)
    awac_repo: str = ""
    awac_path: str = ""
    governance_repo: str = ""
    governance_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "aligned": self.aligned,
            "problems": self.problems,
            "awac_repo": self.awac_repo,
            "awac_path": self.awac_path,
            "governance_repo": self.governance_repo,
            "governance_path": self.governance_path,
        }


def _section_text(doc: str, header_pattern: str) -> str:
    m = re.search(header_pattern, doc)
    if not m:
        return ""
    rest = doc[m.end() :]
    nxt = re.search(r"\n##+ ", rest)
    end = m.end() + nxt.start() if nxt else len(doc)
    return doc[m.start() : end]


def _table_repos(section: str) -> list[str]:
    repos: list[str] = []
    for line in section.splitlines():
        if not line.lstrip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not cells:
            continue
        m = re.fullmatch(r"`([^`]+)`", cells[0])
        if not m:
            continue
        repos.append(m.group(1))
    return repos


def _forbidden_c_names(doc: str) -> list[str]:
    section = _section_text(doc, r"### Categoría C")
    m = re.search(r"Nunca[^.\n]*\(([^)]+)\)", section)
    if not m:
        return []
    return re.findall(r"`([^`]+)`", m.group(1))


def compare(awac: dict, doc: str) -> list[str]:
    """Return a list of human-readable divergence messages. Empty == aligned."""
    problems: list[str] = []

    org = awac.get("org_scaffold") or {}
    if not org:
        return ["awac.yml has no top-level org_scaffold block."]

    for key in (
        "category_a_governance",
        "category_b_public_surface",
        "category_c_product_code",
        "category_d_optional",
        "category_e_cross_org",
    ):
        if key not in org:
            problems.append(f"org_scaffold missing key: {key}")

    for cat in ("A", "B", "C", "D", "E"):
        if not re.search(rf"### Categoría {cat}", doc):
            problems.append(f"governance doc missing '### Categoría {cat}' header")

    doc_a = set(_table_repos(_section_text(doc, r"### Categoría A")))
    awac_a = {r["name"] for r in (org.get("category_a_governance") or {}).get("repos") or [] if r.get("name")}
    missing_a = doc_a - awac_a
    if missing_a:
        problems.append(f"Cat A repos in governance not declared in awac.yml: {sorted(missing_a)}")

    doc_b = set(_table_repos(_section_text(doc, r"### Categoría B")))
    awac_b = {r["name"] for r in (org.get("category_b_public_surface") or {}).get("repos") or [] if r.get("name")}
    missing_b = doc_b - awac_b
    if missing_b:
        problems.append(f"Cat B repos in governance not declared in awac.yml: {sorted(missing_b)}")

    doc_d_raw = _table_repos(_section_text(doc, r"### Categoría D"))
    doc_d_names: set[str] = set()
    doc_d_globs: set[str] = set()
    for n in doc_d_raw:
        if "<" in n and ">" in n:
            doc_d_globs.add(re.sub(r"<[^>]+>", "*", n))
        else:
            doc_d_names.add(n)
    awac_d_repos = (org.get("category_d_optional") or {}).get("repos") or []
    awac_d_names = {r["name"] for r in awac_d_repos if r.get("name")}
    awac_d_globs = {r["glob"] for r in awac_d_repos if r.get("glob")}
    missing_d_names = doc_d_names - awac_d_names
    missing_d_globs = doc_d_globs - awac_d_globs
    if missing_d_names:
        problems.append(f"Cat D named repos in governance not in awac.yml: {sorted(missing_d_names)}")
    if missing_d_globs:
        problems.append(f"Cat D glob patterns in governance not in awac.yml: {sorted(missing_d_globs)}")

    forbidden_doc = set(_forbidden_c_names(doc))
    forbidden_awac = set(
        ((org.get("category_c_product_code") or {}).get("naming_rules") or {}).get("forbidden_names") or []
    )
    if forbidden_doc and forbidden_doc != forbidden_awac:
        problems.append(
            f"forbidden Cat C names diverge — doc: {sorted(forbidden_doc)} vs awac: {sorted(forbidden_awac)}"
        )

    awac_excluded = set(org.get("excluded_names") or [])
    expected_excluded = set(doc_a) | set(doc_b)
    missing_excluded = expected_excluded - awac_excluded
    if missing_excluded:
        problems.append(
            f"governance-derived excluded names missing from awac.yml#excluded_names: {sorted(missing_excluded)}"
        )

    return problems


def run_governance_check(
    *,
    governance_repo: str = DEFAULT_GOVERNANCE_REPO,
    governance_branch: str = DEFAULT_GOVERNANCE_BRANCH,
    governance_doc_path: str = DEFAULT_GOVERNANCE_DOC_PATH,
) -> CheckResult:
    """Clone the governance repo + the registry repo into the local cache and
    compare. Both are fetched via git (uses gh credentials if configured).
    """
    from wsp.registry import registry_repo_and_branch

    awac_repo, awac_branch = registry_repo_and_branch()
    a_org, a_repo = awac_repo.split("/", 1)
    awac_local, _ = git_ops.ensure_repo(a_org, a_repo, ref=awac_branch)
    awac_path = awac_local / "awac.yml"
    if not awac_path.exists():
        raise errors.WspError(
            code="WSP_005", category="schema",
            cause=f"Registry {awac_repo} has no awac.yml.",
            remediation="Set WSP_REGISTRY_REPO to a stack with an awac.yml.",
        )

    g_org, g_repo = governance_repo.split("/", 1)
    g_local, _ = git_ops.ensure_repo(g_org, g_repo, ref=governance_branch)
    doc_path = g_local / governance_doc_path
    if not doc_path.exists():
        raise errors.WspError(
            code="WSP_017", category="filesystem",
            cause=f"Governance doc not found at {governance_repo}/{governance_doc_path}.",
            remediation=f"Verify the path exists in {governance_repo}@{governance_branch}.",
            details={"repo": governance_repo, "path": governance_doc_path},
        )

    awac = yaml.safe_load(awac_path.read_text(encoding="utf-8")) or {}
    doc = doc_path.read_text(encoding="utf-8")
    problems = compare(awac, doc)

    return CheckResult(
        aligned=not problems,
        problems=problems,
        awac_repo=awac_repo,
        awac_path=str(awac_path),
        governance_repo=governance_repo,
        governance_path=str(doc_path),
    )
