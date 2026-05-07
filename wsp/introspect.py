"""Read-only introspection of wsp's local state.

Pure functions that surface paths and metadata the CLI computes
internally — cache location, workspace root, resolved manifest data.

Why this module exists: paths and metadata previously lived in three
places (git_ops.py, the CLI's bootstrap_action, end-user docs). When
docs drifted from code (e.g. v1.5.x docs said `~/.cache/wsp/` while
the code used `~/.wsp/cache/`), users wiped the wrong directory and
got silent no-ops. Centralizing introspection here, and exposing it
via `wsp cache path` / `wsp workspace path|info`, eliminates the gap:
the CLI reports its own state authoritatively, no copy-paste from docs.

All functions are read-only and side-effect free. They never write
files, never network, never spawn subprocesses.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from wsp import git_ops, manifest


def cache_path() -> Path:
    """Return the active wsp cache root (`$WSP_CACHE_DIR` or default)."""
    return git_ops.cache_root()


def find_workspace_root(start: Path) -> Path | None:
    """Walk up from `start` looking for a directory containing `workspace.yml`.

    Returns the directory if found, or None if the search reaches the
    filesystem root without finding one. The caller decides how to handle
    the not-found case (the CLI prints a friendly message; library
    callers may prefer to raise).
    """
    cur = Path(start).resolve()
    while True:
        if (cur / "workspace.yml").exists():
            return cur
        if cur.parent == cur:
            return None
        cur = cur.parent


def workspace_info(start: Path) -> dict[str, Any]:
    """Return a structured snapshot of the workspace at or above `start`.

    Shape (when found):
        {
          "workspace_found": True,
          "path": "<absolute path to workspace root>",
          "manifest_path": "<absolute path to workspace.yml>",
          "name": "<workspace name>",
          "schema": "awac/1" | "awac/2",
          "product": "<product slug>" | None,
          "stacks": [{"ref": "core"} | {"org": "odoopartners", "modules": [...]}],
          "modules": [...],          # Odoo modules (top-level shortcut)
          "extra_repos": [...],
          "deploy_overrides_count": <int>,
          "devvault_overrides_count": <int>,
        }

    Shape (when no workspace found above `start`):
        {"workspace_found": False, "searched_from": "<absolute path>"}
    """
    root = find_workspace_root(start)
    if root is None:
        return {
            "workspace_found": False,
            "searched_from": str(Path(start).resolve()),
        }
    m = manifest.load_manifest(root / "workspace.yml")
    stacks_summary: list[dict[str, Any]] = []
    for s in m.stacks:
        if s.is_odoo_modules:
            stacks_summary.append({
                "kind": "odoo_modules",
                "org": s.odoo_org,
                "modules": list(s.odoo_modules),
            })
        else:
            stacks_summary.append({
                "kind": "stack",
                "ref": s.ref,
            })
    return {
        "workspace_found": True,
        "path": str(root),
        "manifest_path": str(root / "workspace.yml"),
        "name": m.name,
        "schema": m.schema,
        "product": m.product,
        "stacks": stacks_summary,
        "modules": list(m.modules),
        "extra_repos": [{"full": e.full, "branch": e.branch, "path": e.path} for e in m.extra_repos],
        "deploy_overrides_count": len(m.deploy_overrides),
        "devvault_overrides_count": len(m.devvault_overrides),
    }
