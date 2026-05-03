"""Thin wrapper around git for clone/pull/cache operations."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from wsp import errors


def cache_root() -> Path:
    return Path(os.environ.get("WSP_CACHE_DIR", str(Path.home() / ".wsp" / "cache")))


def cache_path(org: str, repo: str) -> Path:
    return cache_root() / org / repo


@dataclass
class GitResult:
    ok: bool
    commit: str | None
    stderr: str


def _run(cmd: list[str], cwd: Path | None = None) -> tuple[int, str, str]:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout, proc.stderr


def have_tool(name: str) -> bool:
    return shutil.which(name) is not None


def ensure_repo(
    org: str,
    repo: str,
    ref: str = "main",
    base_url: str = "https://github.com",
) -> tuple[Path, GitResult]:
    """Ensure org/repo@ref is cached locally, returning (path, result).

    If absent, clone. If present, fetch + checkout. Idempotent.
    """
    target = cache_path(org, repo)
    target.parent.mkdir(parents=True, exist_ok=True)

    url = f"{base_url}/{org}/{repo}.git"

    if not target.exists():
        rc, _out, err = _run(["git", "clone", "--quiet", url, str(target)])
        if rc != 0:
            raise errors.repo_clone_failed(f"{org}/{repo}", ref, err)

    rc, _out, err = _run(["git", "fetch", "--quiet", "origin"], cwd=target)
    if rc != 0:
        raise errors.repo_clone_failed(f"{org}/{repo}", ref, err)

    rc, _out, err = _run(["git", "checkout", "--quiet", ref], cwd=target)
    if rc != 0:
        rc2, _out2, err2 = _run(["git", "checkout", "--quiet", f"origin/{ref}"], cwd=target)
        if rc2 != 0:
            raise errors.repo_clone_failed(f"{org}/{repo}", ref, err + "\n" + err2)

    _run(["git", "reset", "--hard", f"origin/{ref}"], cwd=target)

    rc, out, err = _run(["git", "rev-parse", "HEAD"], cwd=target)
    commit = out.strip() if rc == 0 else None
    return target, GitResult(ok=True, commit=commit, stderr="")


def clone_into(
    org: str,
    repo: str,
    ref: str,
    dest: Path,
    base_url: str = "https://github.com",
) -> GitResult:
    """Clone (or update) org/repo@ref into `dest` (a workspace path).

    If dest already contains a git repo, fetch + checkout instead of re-cloning.
    """
    dest = Path(dest)
    if dest.exists() and (dest / ".git").exists():
        rc, _o, err = _run(["git", "fetch", "--quiet", "origin"], cwd=dest)
        if rc != 0:
            raise errors.repo_clone_failed(f"{org}/{repo}", ref, err)
        rc, _o, err = _run(["git", "checkout", "--quiet", ref], cwd=dest)
        if rc != 0:
            rc2, _o2, err2 = _run(["git", "checkout", "--quiet", f"origin/{ref}"], cwd=dest)
            if rc2 != 0:
                raise errors.repo_clone_failed(f"{org}/{repo}", ref, err + "\n" + err2)
        _run(["git", "merge", "--ff-only", "--quiet", f"origin/{ref}"], cwd=dest)
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        url = f"{base_url}/{org}/{repo}.git"
        rc, _o, err = _run(
            ["git", "clone", "--quiet", "--branch", ref, url, str(dest)]
        )
        if rc != 0:
            rc2, _o2, err2 = _run(["git", "clone", "--quiet", url, str(dest)])
            if rc2 != 0:
                raise errors.repo_clone_failed(f"{org}/{repo}", ref, err + "\n" + err2)
            rc3, _o3, err3 = _run(["git", "checkout", "--quiet", ref], cwd=dest)
            if rc3 != 0:
                raise errors.repo_clone_failed(f"{org}/{repo}", ref, err3)

    rc, out, _ = _run(["git", "rev-parse", "HEAD"], cwd=dest)
    return GitResult(ok=True, commit=out.strip() if rc == 0 else None, stderr="")


def fetch_only(repo_path: Path) -> bool:
    """Run `git fetch --quiet origin` on an existing repo. Return True on success.

    Used by `wsp status` so we can compare local state against upstream
    without mutating working tree or HEAD.
    """
    if not (repo_path / ".git").exists():
        return False
    rc, _o, _e = _run(["git", "fetch", "--quiet", "origin"], cwd=repo_path)
    return rc == 0


def head_commit(repo_path: Path) -> str | None:
    rc, out, _ = _run(["git", "rev-parse", "HEAD"], cwd=repo_path)
    return out.strip() if rc == 0 else None


def remote_commit(repo_path: Path, ref: str) -> str | None:
    rc, out, _ = _run(["git", "rev-parse", f"origin/{ref}"], cwd=repo_path)
    return out.strip() if rc == 0 else None


def commit_distance(repo_path: Path, base: str, head: str) -> tuple[int, int]:
    """Return (behind, ahead) of `head` vs `base` — counts in `base..head` and `head..base`.

    Convention: "behind base by N" = `base..head` has N commits MISSING from head
    relative to base. We compute it as `head..base` count for "behind", and
    `base..head` count for "ahead" — i.e. ahead/behind from `head`'s point of view
    relative to `base`.
    """
    rc, out, _ = _run(
        ["git", "rev-list", "--left-right", "--count", f"{base}...{head}"],
        cwd=repo_path,
    )
    if rc != 0 or not out.strip():
        return (0, 0)
    parts = out.strip().split()
    if len(parts) != 2:
        return (0, 0)
    try:
        behind = int(parts[0])
        ahead = int(parts[1])
    except ValueError:
        return (0, 0)
    return (behind, ahead)


def porcelain_status(repo_path: Path) -> list[str]:
    """List of `git status --porcelain` lines (modified/untracked files)."""
    rc, out, _ = _run(["git", "status", "--porcelain"], cwd=repo_path)
    if rc != 0:
        return []
    return [ln for ln in out.splitlines() if ln.strip()]


def current_branch(repo_path: Path) -> str | None:
    rc, out, _ = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_path)
    if rc != 0:
        return None
    branch = out.strip()
    return branch if branch and branch != "HEAD" else None
