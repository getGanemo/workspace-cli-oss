"""Compose `.agents/` and CLAUDE.md/AGENTS.md from active stacks.

Strategy:
  - For each stack (in order from workspace.yml), copy its rules/, skills/,
    and workflows/ subtrees into the workspace's `.agents/`. Later stacks
    win on filename collisions, with a recorded warning.
  - Generate CLAUDE.md (canonical) with a header listing the active stacks
    and a preserved <!-- @awac:editable --> block. Mirror to AGENTS.md.

This is intentionally simple for v1. Symlinks are not used to keep behavior
identical on Windows + macOS + Linux.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from wsp import __version__ as WSP_VERSION
from wsp import errors


def _robust_rmtree(path: Path, retries: int = 3) -> None:
    """rmtree that survives Windows ACL quirks.

    Strategy on PermissionError / OSError:
      1. Walk the tree and chmod +w everything.
      2. Retry rmtree.
      3. If still failing after `retries` attempts, raise WspError WSP_022
         with a remediation telling the user to close any editor with
         files in the dir open and retry — or to delete it manually.

    This is the failure mode bug #13 captured in v1.4.1: Windows users
    running `wsp bootstrap` twice would hit a PermissionError because git
    cloned read-only files into the cache OR because an editor held a
    file lock on .agents/rules/<file>.
    """
    if not path.exists():
        return

    def _on_error(func, p, exc_info):
        # Make writable, then retry the func once.
        try:
            os.chmod(p, stat.S_IWRITE | stat.S_IREAD)
            func(p)
        except Exception:
            raise

    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            shutil.rmtree(path, onerror=_on_error)
            return
        except (PermissionError, OSError) as exc:
            last_exc = exc
            # Walk the tree and force +w on everything before next try.
            try:
                for root, dirs, files in os.walk(path):
                    for d in dirs:
                        try:
                            os.chmod(os.path.join(root, d), stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
                        except OSError:
                            pass
                    for f in files:
                        try:
                            os.chmod(os.path.join(root, f), stat.S_IWRITE | stat.S_IREAD)
                        except OSError:
                            pass
            except OSError:
                pass
            time.sleep(0.1 * (attempt + 1))

    raise errors.WspError(
        code="WSP_022",
        category="filesystem",
        cause=(
            f"Could not remove {path}: {last_exc}. "
            "On Windows this usually means an editor (VS Code / Cursor / Explorer) "
            "has a file inside this directory open, or the directory contains "
            "git-cloned files marked read-only by Windows ACL."
        ),
        remediation=(
            f"Close any editor or terminal with files in {path} open, then retry "
            f"`wsp bootstrap`. If it still fails, delete {path} manually "
            "(`rmdir /s /q .agents` on Windows; `rm -rf .agents` elsewhere) "
            "and run `wsp bootstrap` again. Alternatively: pass --no-clean "
            "to bootstrap to skip cleanup of existing .agents/."
        ),
        details={"path": str(path), "last_error": str(last_exc) if last_exc else None},
    )

AGENT_DIRS = ("rules", "skills", "workflows")
EDITABLE_START = "<!-- @awac:editable-start -->"
EDITABLE_END = "<!-- @awac:editable-end -->"
HEADER_START = "<!-- @awac:header-start -->"
HEADER_END = "<!-- @awac:header-end -->"


@dataclass
class ComposeReport:
    workspace: Path
    agent_dirs_written: list[str] = field(default_factory=list)
    file_count: int = 0
    collisions: list[dict[str, str]] = field(default_factory=list)
    canonical: str = ""
    mirrors: list[str] = field(default_factory=list)


def _copy_subtree(src: Path, dest: Path, source_label: str, collisions: list[dict[str, str]]) -> int:
    if not src.exists() or not src.is_dir():
        return 0
    count = 0
    for item in src.rglob("*"):
        if item.is_dir():
            continue
        rel = item.relative_to(src)
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            collisions.append({"file": str((dest.name / rel).as_posix()), "winner": source_label})
        shutil.copy2(item, target)
        count += 1
    return count


def compose_agents(
    workspace_root: Path,
    stacks: list[tuple[str, Path]],
    *,
    clean: bool = True,
) -> ComposeReport:
    """Copy rules/skills/workflows from each stack into <workspace>/.agents/.

    `stacks` is a list of (label, stack_root_path). Order matters: later wins.

    When `clean=True` (default), wipes existing `.agents/` before recomposing
    for full determinism. When `clean=False`, copies on top — useful when
    the user wants to preserve a partially-built workspace or work around
    Windows ACL issues (see WSP_022).
    """
    workspace_root = Path(workspace_root)
    agents_dir = workspace_root / ".agents"
    if clean:
        _robust_rmtree(agents_dir)
    agents_dir.mkdir(parents=True, exist_ok=True)

    report = ComposeReport(workspace=workspace_root)
    for sub in AGENT_DIRS:
        (agents_dir / sub).mkdir(parents=True, exist_ok=True)
        report.agent_dirs_written.append(sub)

    for label, root in stacks:
        for sub in AGENT_DIRS:
            count = _copy_subtree(root / sub, agents_dir / sub, label, report.collisions)
            report.file_count += count

    return report


def render_agent_file(
    workspace_name: str,
    stacks_summary: list[dict[str, str]],
    editable_block: str | None,
    extras: dict[str, str] | None = None,
) -> str:
    """Build the canonical CLAUDE.md / AGENTS.md content."""
    extras = extras or {}
    lines: list[str] = []
    lines.append(HEADER_START)
    lines.append(f"# Workspace: {workspace_name}")
    lines.append("")
    lines.append(
        "This file is generated by [`wsp`](https://github.com/getGanemo/workspace-cli) "
        f"(v{WSP_VERSION}). Edit only inside the @awac:editable block — everything else "
        "is regenerated by `wsp bootstrap`."
    )
    lines.append("")
    lines.append("## Active stacks")
    lines.append("")
    for s in stacks_summary:
        line = f"- **{s['label']}** — `{s['repo']}@{s['ref']}`"
        if s.get("commit"):
            line += f" (`{s['commit'][:8]}`)"
        lines.append(line)
    lines.append("")
    if extras.get("repos_summary"):
        lines.append("## Cloned product repos")
        lines.append("")
        lines.append(extras["repos_summary"])
        lines.append("")
    lines.append("Agent assets live under `.agents/{rules,skills,workflows}/`.")
    lines.append(HEADER_END)
    lines.append("")
    lines.append(EDITABLE_START)
    if editable_block is None:
        lines.append("<!--")
        lines.append("Hand-authored content for this workspace goes here. `wsp bootstrap`")
        lines.append("preserves anything between the @awac:editable markers.")
        lines.append("-->")
    else:
        lines.append(editable_block.strip("\n"))
    lines.append(EDITABLE_END)
    lines.append("")
    return "\n".join(lines)


def extract_editable_block(text: str) -> str | None:
    if not text:
        return None
    pattern = re.compile(
        re.escape(EDITABLE_START) + r"\n?(.*?)\n?" + re.escape(EDITABLE_END),
        re.DOTALL,
    )
    match = pattern.search(text)
    return match.group(1) if match else None


def write_agent_files(
    workspace_root: Path,
    canonical_name: str,
    mirror_names: Iterable[str],
    workspace_name: str,
    stacks_summary: list[dict[str, str]],
    repos_summary: str | None = None,
) -> tuple[str, list[str]]:
    workspace_root = Path(workspace_root)
    canonical_path = workspace_root / canonical_name
    existing = canonical_path.read_text(encoding="utf-8") if canonical_path.exists() else ""
    editable = extract_editable_block(existing)
    content = render_agent_file(
        workspace_name=workspace_name,
        stacks_summary=stacks_summary,
        editable_block=editable,
        extras={"repos_summary": repos_summary} if repos_summary else None,
    )
    canonical_path.write_text(content, encoding="utf-8")

    mirrors_written: list[str] = []
    for mirror in mirror_names:
        mp = workspace_root / mirror
        mp.write_text(content, encoding="utf-8")
        mirrors_written.append(mirror)
    return canonical_name, mirrors_written
