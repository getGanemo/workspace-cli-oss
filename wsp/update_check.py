"""Best-effort check for newer wsp releases on GitHub.

Runs at most once per `UPDATE_CHECK_INTERVAL_HOURS` (default 24) and prints a
single-line warning to stderr if a newer release exists. Never blocks
execution: any failure (network, auth, parse) is silently swallowed so the
CLI keeps working in air-gapped or rate-limited environments.

Disabled when:
  - WSP_NO_UPDATE_CHECK=1 in env
  - --no-update-check flag in argv (handled at cli.py level)
  - last check was < UPDATE_CHECK_INTERVAL_HOURS ago
  - the running version cannot be parsed (dev installs typically)

Privacy notes:
  - Only outbound call is to api.github.com/repos/<owner>/<repo>/releases/latest
    which is the same public endpoint anyone can hit.
  - No machine identifiers, no telemetry, no callback to Ganemo infra.
  - For the private repo, uses `gh api` (already authenticated by the user
    for cache resolution) so we don't ship tokens.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

UPDATE_CHECK_INTERVAL_HOURS = 24
HTTP_TIMEOUT_SECONDS = 2.0
ENV_DISABLE = "WSP_NO_UPDATE_CHECK"

# The repo we check against. The PRIVATE wheel is published to
# `getGanemo/workspace-cli`; the PUBLIC OSS wheel is published to
# `getGanemo/workspace-cli-oss`. The two builds carry different defaults
# via the `_DEFAULT_RELEASES_REPO` constant.
_DEFAULT_RELEASES_REPO = "getGanemo/workspace-cli-oss"


def _check_state_path() -> Path:
    base = os.environ.get("WSP_CACHE_DIR")
    if base:
        return Path(base) / "last_update_check.json"
    return Path.home() / ".wsp" / "last_update_check.json"


def _load_last_check() -> dict | None:
    p = _check_state_path()
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _save_last_check(latest_version: str | None) -> None:
    p = _check_state_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps({"checked_at": int(time.time()), "latest": latest_version}),
            encoding="utf-8",
        )
    except OSError:
        pass


def _parse_version(s: str) -> tuple[int, ...] | None:
    s = s.strip().lstrip("v")
    if not s:
        return None
    parts = s.split("-", 1)[0].split(".")
    try:
        return tuple(int(p) for p in parts[:3])
    except ValueError:
        return None


def _version_lt(a: str, b: str) -> bool:
    pa, pb = _parse_version(a), _parse_version(b)
    if pa is None or pb is None:
        return False
    return pa < pb


def _fetch_latest_via_gh(repo: str) -> str | None:
    """Use `gh api` so the call is authenticated for private repos.

    Returns the tag_name (e.g. 'v1.4.0') or None on any failure.
    """
    if shutil.which("gh") is None:
        return None
    try:
        out = subprocess.run(
            ["gh", "api", f"repos/{repo}/releases/latest", "--jq", ".tag_name"],
            capture_output=True,
            text=True,
            timeout=HTTP_TIMEOUT_SECONDS,
            check=False,
        )
        if out.returncode != 0:
            return None
        tag = out.stdout.strip()
        return tag or None
    except (subprocess.TimeoutExpired, OSError):
        return None


def _format_warning(current: str, latest: str, repo: str) -> str:
    pa, pb = _parse_version(current), _parse_version(latest)
    if pa and pb and pb[0] - pa[0] >= 1:
        return (
            f"⚠ wsp {latest} available (you have {current}, "
            f"{pb[0] - pa[0]} major version(s) behind). Read the changelog before upgrading:\n"
            f"  https://github.com/{repo}/blob/main/CHANGELOG.md\n"
            f"  Upgrade: gh release download --repo {repo} --pattern '*.whl' --dir /tmp/wsp && pipx install --force /tmp/wsp/wsp-*.whl\n"
            f"  (Disable with {ENV_DISABLE}=1)"
        )
    return (
        f"⚠ wsp {latest} available (you have {current}). Upgrade with:\n"
        f"  gh release download --repo {repo} --pattern '*.whl' --dir /tmp/wsp && pipx install --force /tmp/wsp/wsp-*.whl\n"
        f"  (Disable with {ENV_DISABLE}=1)"
    )


def maybe_check_for_updates(
    current_version: str,
    repo: str | None = None,
    *,
    force: bool = False,
) -> str | None:
    """Run the update check. Returns the warning string if printed, else None.

    Designed to be called once at CLI startup, before subcommand dispatch.
    Caller decides whether to print to stderr; this function does NOT print
    on its own so tests can assert on the return value.
    """
    if os.environ.get(ENV_DISABLE):
        return None

    repo = repo or _DEFAULT_RELEASES_REPO

    last = _load_last_check() if not force else None
    if last:
        elapsed_hours = (time.time() - last.get("checked_at", 0)) / 3600.0
        if elapsed_hours < UPDATE_CHECK_INTERVAL_HOURS:
            cached_latest = last.get("latest")
            if cached_latest and _version_lt(current_version, cached_latest.lstrip("v")):
                return _format_warning(current_version, cached_latest.lstrip("v"), repo)
            return None

    tag = _fetch_latest_via_gh(repo)
    if not tag:
        # Save the attempt anyway so we don't retry every command for 24h.
        _save_last_check(None)
        return None

    latest = tag.lstrip("v")
    _save_last_check(latest)

    if _version_lt(current_version, latest):
        return _format_warning(current_version, latest, repo)
    return None


def emit_update_warning_if_any(current_version: str, repo: str | None = None) -> None:
    """Convenience wrapper: run the check and print warning to stderr."""
    try:
        msg = maybe_check_for_updates(current_version, repo=repo)
        if msg:
            print(msg, file=sys.stderr)
    except Exception:
        pass
