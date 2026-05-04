"""Load and resolve the AWaC registry (shortcuts + templates + org-scaffold rules).

The registry lives in `<WSP_REGISTRY_REPO>/awac.yml`, default
`getGanemo/agent-stack-core-oss/awac.yml` on branch `main`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from wsp import errors, git_ops

DEFAULT_REGISTRY_REPO = "getGanemo/agent-stack-core-oss"
DEFAULT_REGISTRY_BRANCH = "main"

# Where seed READMEs and scaffold-stack output point users to read about
# governance conventions. Override with WSP_GOVERNANCE_DOC when adopting AWaC
# for an organization with its own governance document.
DEFAULT_GOVERNANCE_DOC = "https://awac.ganemo.com/governance/"


def governance_doc_url() -> str:
    """Resolve the governance doc URL the CLI references in seed output.

    Order: WSP_GOVERNANCE_DOC env var > DEFAULT_GOVERNANCE_DOC.
    """
    return os.environ.get("WSP_GOVERNANCE_DOC", DEFAULT_GOVERNANCE_DOC)


import re as _re

# A template is "product-specific" if its path lives under
# <some-org>/agent-stack/templates/. Such templates clone product repos and
# embed the workspace into a product's deploy/secrets flow, so we require
# explicit confirmation before scaffolding from them. The OSS build does not
# hardcode any specific product org — any org that follows the AWaC
# `<org>/agent-stack/templates/<file>.yml` convention qualifies.
_PRODUCT_TEMPLATE_PATH_RE = _re.compile(r"^[a-z0-9][a-z0-9_-]*/agent-stack/templates/")


@dataclass
class Template:
    name: str
    description: str
    path: str  # e.g. "<your-product>/agent-stack/templates/feature.yml"
    composes_stacks: list[str] = field(default_factory=list)
    clones_repos: list[str] = field(default_factory=list)
    embeds_in_product_flow: str | None = None

    @property
    def is_product_template(self) -> bool:
        if not self.path:
            return False
        return bool(_PRODUCT_TEMPLATE_PATH_RE.match(self.path))

    @property
    def product_org(self) -> str | None:
        if not self.is_product_template:
            return None
        return self.path.split("/", 1)[0]

    @property
    def requires_confirmation(self) -> bool:
        return self.is_product_template

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "path": self.path,
            "requires_confirmation": self.requires_confirmation,
            "composes_stacks": list(self.composes_stacks),
            "clones_repos": list(self.clones_repos),
            "embeds_in_product_flow": self.embeds_in_product_flow,
        }


@dataclass
class StackRef:
    """A resolved stack: full org/repo plus the shortcut alias if any."""

    org: str
    repo: str
    shortcut: str | None = None

    @property
    def full(self) -> str:
        return f"{self.org}/{self.repo}"


@dataclass
class Registry:
    raw: dict[str, Any]
    repo: str
    branch: str
    local_path: Path
    shortcuts: dict[str, str] = field(default_factory=dict)
    templates: list[Template] = field(default_factory=list)
    agent_context: dict[str, Any] = field(default_factory=dict)

    def resolve(self, token: str) -> StackRef:
        """Resolve a stacks: entry into a StackRef.

        - "core"             -> registry lookup
        - "org/repo"         -> literal
        """
        if "/" in token:
            org, repo = token.split("/", 1)
            return StackRef(org=org, repo=repo)
        if token not in self.shortcuts:
            raise errors.shortcut_unknown(token, sorted(self.shortcuts.keys()))
        full = self.shortcuts[token]
        org, repo = full.split("/", 1)
        return StackRef(org=org, repo=repo, shortcut=token)

    def template(self, name: str) -> Template:
        for t in self.templates:
            if t.name == name:
                return t
        raise errors.template_unknown(name, [t.name for t in self.templates])


def registry_repo_and_branch() -> tuple[str, str]:
    return (
        os.environ.get("WSP_REGISTRY_REPO", DEFAULT_REGISTRY_REPO),
        os.environ.get("WSP_REGISTRY_BRANCH", DEFAULT_REGISTRY_BRANCH),
    )


def load_registry() -> Registry:
    repo_full, branch = registry_repo_and_branch()
    org, repo = repo_full.split("/", 1)
    try:
        local, _ = git_ops.ensure_repo(org, repo, ref=branch)
    except errors.WspError as exc:
        raise errors.registry_fetch_failed(repo_full, branch, exc.details.get("stderr", "") if exc.details else "")
    awac_yml = local / "awac.yml"
    if not awac_yml.exists():
        raise errors.WspError(
            code="WSP_005",
            category="schema",
            cause=f"Registry repo {repo_full}@{branch} has no awac.yml.",
            remediation="Point WSP_REGISTRY_REPO at a stack repo with an awac.yml.",
        )
    raw = yaml.safe_load(awac_yml.read_text(encoding="utf-8")) or {}
    shortcuts = dict(raw.get("shortcuts") or {})
    templates = [
        Template(name=t["name"], description=t.get("description", ""), path=t["path"])
        for t in (raw.get("templates") or [])
    ]
    agent_context = dict(raw.get("agent_context") or {})
    return Registry(
        raw=raw,
        repo=repo_full,
        branch=branch,
        local_path=local,
        shortcuts=shortcuts,
        templates=templates,
        agent_context=agent_context,
    )


def _parse_template_meta_block(text: str) -> dict[str, Any] | None:
    """Look for a '# wsp-template-meta:' YAML block at the top of a template file.

    Format:
        # wsp-template-meta:
        # composes_stacks: ['atlas']
        # clones_repos: ['atlas-org/atlas-api']
        # embeds_in_product_flow: atlas
    """
    lines = text.split("\n")
    if not lines:
        return None
    start = None
    for i, line in enumerate(lines[:30]):
        if line.strip().startswith("#") and "wsp-template-meta" in line:
            start = i
            break
    if start is None:
        return None
    block_lines: list[str] = []
    for line in lines[start + 1 : start + 25]:
        stripped = line.lstrip()
        if not stripped.startswith("#"):
            break
        block_lines.append(stripped[1:].lstrip())
    if not block_lines:
        return None
    try:
        meta = yaml.safe_load("\n".join(block_lines)) or {}
    except yaml.YAMLError:
        return None
    return meta if isinstance(meta, dict) else None


def enrich_template_metadata(template: Template) -> Template:
    """Populate composes_stacks/clones_repos/embeds_in_product_flow from disk.

    For product templates, infer composes_stacks from the template's `stacks:`
    list and clones_repos from the product stack's awac.yml#repos when the
    template doesn't declare them via a `# wsp-template-meta:` block.
    """
    text = ""
    parts = template.path.split("/")
    if len(parts) >= 3:
        org, repo = parts[0], parts[1]
        rest = "/".join(parts[2:])
        try:
            local, _ = git_ops.ensure_repo(org, repo)
            file_path = local / rest
            if file_path.exists():
                text = file_path.read_text(encoding="utf-8")
        except errors.WspError:
            text = ""

    meta = _parse_template_meta_block(text) if text else None

    composes: list[str] = []
    clones: list[str] = []
    embeds: str | None = None

    if meta:
        composes = list(meta.get("composes_stacks") or [])
        clones = list(meta.get("clones_repos") or [])
        if "embeds_in_product_flow" in meta:
            embeds = meta["embeds_in_product_flow"]

    if template.is_product_template:
        if not composes:
            try:
                tpl = yaml.safe_load(text) or {}
                if isinstance(tpl, dict):
                    composes = [
                        s if isinstance(s, str) else s.get("ref", "")
                        for s in (tpl.get("stacks") or [])
                        if isinstance(s, (str, dict))
                    ]
                    composes = [s for s in composes if s]
            except yaml.YAMLError:
                pass
        if not clones:
            org = template.product_org
            if org:
                try:
                    local, _ = git_ops.ensure_repo(org, "agent-stack")
                    awac = local / "awac.yml"
                    if awac.exists():
                        ay = yaml.safe_load(awac.read_text(encoding="utf-8")) or {}
                        for repo_decl in ay.get("repos") or []:
                            r_org = repo_decl.get("org", org)
                            r_name = repo_decl.get("name")
                            if r_name:
                                clones.append(f"{r_org}/{r_name}")
                except errors.WspError:
                    pass
        if not embeds:
            org = template.product_org
            if org:
                try:
                    local, _ = git_ops.ensure_repo(org, "agent-stack")
                    awac = local / "awac.yml"
                    if awac.exists():
                        ay = yaml.safe_load(awac.read_text(encoding="utf-8")) or {}
                        embeds = ay.get("product")
                except errors.WspError:
                    pass

    template.composes_stacks = composes
    template.clones_repos = clones
    template.embeds_in_product_flow = embeds
    return template


def fetch_template_text(registry: Registry, template: Template) -> str:
    """Read a template file from a stack repo, ensuring the stack is cached."""
    parts = template.path.split("/")
    if len(parts) < 3:
        raise errors.WspError(
            code="WSP_002",
            category="schema",
            cause=f"Template path '{template.path}' is malformed.",
            remediation="Expected '<org>/<repo>/<rest>'.",
        )
    org, repo = parts[0], parts[1]
    rest = "/".join(parts[2:])
    local, _ = git_ops.ensure_repo(org, repo)
    file_path = local / rest
    if not file_path.exists():
        raise errors.WspError(
            code="WSP_002",
            category="filesystem",
            cause=f"Template file not found: {template.path}.",
            remediation="Check the registry's templates: list points at an existing file.",
        )
    return file_path.read_text(encoding="utf-8")
