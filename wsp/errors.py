"""Stable error catalog for wsp.

Every error agents may surface to a model carries:
  - code        stable identifier (WSP_NNN)
  - category    coarse class for routing
  - cause       short factual description
  - remediation actionable next step

Categories: input | env | network | filesystem | schema | internal
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class WspError(Exception):
    code: str
    category: str
    cause: str
    remediation: str
    details: dict[str, Any] | None = None

    def __str__(self) -> str:
        return f"[{self.code}] {self.cause} — {self.remediation}"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if d.get("details") is None:
            d.pop("details", None)
        return d


def manifest_missing(path: str) -> WspError:
    return WspError(
        code="WSP_001",
        category="filesystem",
        cause=f"workspace.yml not found at {path}",
        remediation="Run `wsp init <name>` to create one, or cd into a workspace directory.",
        details={"path": path},
    )


def manifest_invalid(reason: str, path: str) -> WspError:
    return WspError(
        code="WSP_002",
        category="schema",
        cause=f"workspace.yml at {path} is invalid: {reason}",
        remediation="Check the manifest against `wsp schema workspace`.",
        details={"path": path, "reason": reason},
    )


def shortcut_unknown(shortcut: str, available: list[str]) -> WspError:
    return WspError(
        code="WSP_003",
        category="input",
        cause=f"Unknown stack shortcut '{shortcut}'.",
        remediation="Run `wsp shortcuts` to list valid names, or pass full org/repo.",
        details={"shortcut": shortcut, "available": available},
    )


def repo_clone_failed(repo: str, ref: str, stderr: str) -> WspError:
    return WspError(
        code="WSP_004",
        category="network",
        cause=f"Failed to clone {repo}@{ref}.",
        remediation="Check `gh auth status` and that you have access to the repo.",
        details={"repo": repo, "ref": ref, "stderr": stderr[-2000:]},
    )


def registry_fetch_failed(repo: str, ref: str, stderr: str) -> WspError:
    return WspError(
        code="WSP_005",
        category="network",
        cause=f"Could not fetch the AWaC registry from {repo}@{ref}.",
        remediation=(
            "Check WSP_REGISTRY_REPO/WSP_REGISTRY_BRANCH and `gh auth status`. "
            "Default registry is getGanemo/agent-stack-core-oss@main."
        ),
        details={"repo": repo, "ref": ref, "stderr": stderr[-2000:]},
    )


def target_not_empty(path: str) -> WspError:
    return WspError(
        code="WSP_006",
        category="filesystem",
        cause=f"Target directory {path} already contains files.",
        remediation="Use a fresh directory, or pass --target to point elsewhere.",
        details={"path": path},
    )


def required_tool_missing(tool: str, install_hint: str) -> WspError:
    return WspError(
        code="WSP_007",
        category="env",
        cause=f"Required tool not found on PATH: {tool}.",
        remediation=install_hint,
        details={"tool": tool},
    )


def template_unknown(name: str, available: list[str]) -> WspError:
    return WspError(
        code="WSP_008",
        category="input",
        cause=f"Unknown template '{name}'.",
        remediation="Run `wsp templates` to list available templates.",
        details={"template": name, "available": available},
    )


def stack_metadata_missing(stack_repo: str) -> WspError:
    return WspError(
        code="WSP_009",
        category="schema",
        cause=f"Stack {stack_repo} is missing awac.yml.",
        remediation="Add an awac.yml to the stack repo (see schema `wsp schema awac`).",
        details={"stack": stack_repo},
    )


def schema_unknown(name: str) -> WspError:
    return WspError(
        code="WSP_010",
        category="input",
        cause=f"Unknown schema name '{name}'.",
        remediation="Use one of: workspace, awac, lock.",
        details={"schema": name},
    )


def schema_version_unsupported(found: str, supported: list[str]) -> WspError:
    return WspError(
        code="WSP_011",
        category="schema",
        cause=f"Manifest schema '{found}' is not supported by this CLI.",
        remediation=f"Upgrade wsp or downgrade the manifest. Supported: {', '.join(supported)}.",
        details={"found": found, "supported": supported},
    )


def overrides_require_awac_v2(current_schema: str) -> WspError:
    return WspError(
        code="WSP_018",
        category="schema",
        cause=(
            f"deploy_overrides/devvault_overrides require schema awac/2; "
            f"current is {current_schema}"
        ),
        remediation="Set 'schema: awac/2' at the top of your workspace.yml.",
        details={"current_schema": current_schema, "required_schema": "awac/2"},
    )


def override_target_not_available(
    component: str, attempted_target: str, available: list[str]
) -> WspError:
    return WspError(
        code="WSP_019",
        category="schema",
        cause=(
            f"workspace deploy_override sets target={attempted_target} for "
            f"component {component}, but stack only allows "
            f"targets_available={available}"
        ),
        remediation=(
            "Choose one of the available targets, or update the stack's "
            "targets_available list (canonical change in the stack repo)."
        ),
        details={
            "component": component,
            "attempted": attempted_target,
            "available": available,
        },
    )


def product_template_requires_confirmation(
    template: str,
    composes_stacks: list[str] | None = None,
    clones_repos: list[str] | None = None,
) -> WspError:
    composes_stacks = composes_stacks or []
    clones_repos = clones_repos or []
    impact_bits: list[str] = []
    if clones_repos:
        impact_bits.append(f"clones_repos={clones_repos}")
    if composes_stacks:
        impact_bits.append(f"composes_stacks={composes_stacks}")
    impact = (" Impact: " + "; ".join(impact_bits) + ".") if impact_bits else ""
    return WspError(
        code="WSP_020",
        category="input",
        cause=(
            f"Template {template!r} is a product-specific template. "
            "It will clone product repos and embed this workspace in the "
            f"product's deploy/secrets flow.{impact}"
        ),
        remediation=(
            "Confirm with --yes if intentional, or use --interactive to choose. "
            "To see the impact: 'wsp templates --json' shows clones_repos and "
            "composes_stacks for each template."
        ),
        details={
            "template": template,
            "composes_stacks": composes_stacks,
            "clones_repos": clones_repos,
        },
    )


def stack_metadata_drift(drifted_files: list[str]) -> WspError:
    return WspError(
        code="WSP_021",
        category="schema",
        cause=f"{len(drifted_files)} stack metadata file(s) drifted from lock: {drifted_files}",
        remediation=(
            "Edit canonical files in the stack repo, push, then 'wsp sync' "
            "here. To intentionally diverge for this workspace, use "
            "workspace.yml#deploy_overrides or #devvault_overrides instead."
        ),
        details={"drifted_files": drifted_files},
    )
