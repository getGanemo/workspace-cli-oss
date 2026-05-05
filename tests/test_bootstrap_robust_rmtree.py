"""Tests for the WSP_022 fix: bootstrap survives Windows ACL / read-only files.

Bug #13 (2026-05-05): on Windows, `wsp bootstrap` failed when re-run because
git-cloned files in .agents/rules/ had been marked read-only by Windows ACL,
or because an editor (VS Code / Cursor) held a file lock. shutil.rmtree
raised PermissionError and the workspace was left half-composed.

Fix: composer._robust_rmtree retries with chmod +w + sleep, and on final
failure raises a structured WSP_022 error with a clear remediation. Also
adds `--no-clean` flag to bootstrap to skip the cleanup entirely.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path
from unittest.mock import patch

import pytest

from wsp import composer, errors


def test_robust_rmtree_no_op_on_missing_path(tmp_path):
    target = tmp_path / "does_not_exist"
    composer._robust_rmtree(target)  # should not raise


def test_robust_rmtree_succeeds_on_normal_dir(tmp_path):
    target = tmp_path / "normal"
    target.mkdir()
    (target / "a.txt").write_text("hello")
    (target / "sub").mkdir()
    (target / "sub" / "b.txt").write_text("world")
    composer._robust_rmtree(target)
    assert not target.exists()


def test_robust_rmtree_handles_read_only_files(tmp_path):
    """Simulates a git-cloned read-only file inside .agents/rules/."""
    target = tmp_path / "with_readonly"
    target.mkdir()
    f = target / "readonly.md"
    f.write_text("rule")
    os.chmod(f, stat.S_IREAD)  # mimic Windows ACL setting read-only
    try:
        composer._robust_rmtree(target)
        assert not target.exists()
    finally:
        # Restore so pytest cleanup works even if rmtree didn't.
        if f.exists():
            os.chmod(f, stat.S_IWRITE | stat.S_IREAD)


def test_robust_rmtree_raises_wsp_022_when_unrecoverable(tmp_path, monkeypatch):
    """If rmtree fails permanently (every retry), raise WSP_022 structured error."""
    target = tmp_path / "locked"
    target.mkdir()
    (target / "f.txt").write_text("x")

    call_count = {"n": 0}
    def always_fails(*args, **kwargs):
        call_count["n"] += 1
        raise PermissionError(f"Access denied (call {call_count['n']})")

    monkeypatch.setattr("wsp.composer.shutil.rmtree", always_fails)

    with pytest.raises(errors.WspError) as exc_info:
        composer._robust_rmtree(target, retries=2)

    err = exc_info.value
    assert err.code == "WSP_022"
    assert err.category == "filesystem"
    assert "editor" in err.cause.lower() or "ACL" in err.cause or "lock" in err.cause.lower()
    assert "rmdir" in err.remediation or "rm -rf" in err.remediation or "--no-clean" in err.remediation
    assert err.details["path"] == str(target)
    assert call_count["n"] == 2  # retried `retries` times


def test_compose_agents_clean_false_preserves_existing(tmp_path):
    """--no-clean should not invoke rmtree; existing .agents/ is preserved."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    agents_dir = workspace / ".agents"
    agents_dir.mkdir()
    (agents_dir / "preserved.txt").write_text("dont touch me")

    # No stacks → nothing copied. Just verify the existing file survives.
    composer.compose_agents(workspace, stacks=[], clean=False)
    assert (agents_dir / "preserved.txt").read_text() == "dont touch me"


def test_compose_agents_clean_true_wipes_existing(tmp_path):
    """Default clean=True should remove existing .agents/ contents."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    agents_dir = workspace / ".agents"
    agents_dir.mkdir()
    (agents_dir / "stale.txt").write_text("should be wiped")

    composer.compose_agents(workspace, stacks=[], clean=True)
    assert not (agents_dir / "stale.txt").exists()
    # The dir itself is recreated (mkdir(exist_ok=True)).
    assert agents_dir.exists()
