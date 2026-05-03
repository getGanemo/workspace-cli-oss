from pathlib import Path

from wsp import composer


def _make_stack(root: Path, name: str, files: dict[str, str]) -> Path:
    stack = root / name
    for rel, content in files.items():
        p = stack / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return stack


def test_compose_copies_subtrees(tmp_path):
    a = _make_stack(tmp_path, "stack-a", {
        "rules/one.md": "A1",
        "skills/s/SKILL.md": "S1",
        "workflows/w.md": "W1",
    })
    b = _make_stack(tmp_path, "stack-b", {
        "rules/two.md": "B2",
    })
    workspace = tmp_path / "ws"
    workspace.mkdir()
    report = composer.compose_agents(workspace, [("a", a), ("b", b)])
    assert (workspace / ".agents/rules/one.md").read_text() == "A1"
    assert (workspace / ".agents/rules/two.md").read_text() == "B2"
    assert (workspace / ".agents/skills/s/SKILL.md").read_text() == "S1"
    assert report.file_count == 4
    assert report.collisions == []


def test_compose_collisions_last_wins(tmp_path):
    a = _make_stack(tmp_path, "a", {"rules/dup.md": "FROM-A"})
    b = _make_stack(tmp_path, "b", {"rules/dup.md": "FROM-B"})
    workspace = tmp_path / "ws"
    workspace.mkdir()
    report = composer.compose_agents(workspace, [("a", a), ("b", b)])
    assert (workspace / ".agents/rules/dup.md").read_text() == "FROM-B"
    assert any(c["winner"] == "b" for c in report.collisions)


def test_editable_block_preserved(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "CLAUDE.md").write_text(
        "# old auto stuff\n"
        + composer.EDITABLE_START + "\nMy hand-written section.\n" + composer.EDITABLE_END + "\n"
    )
    composer.write_agent_files(
        workspace_root=workspace,
        canonical_name="CLAUDE.md",
        mirror_names=["AGENTS.md"],
        workspace_name="demo",
        stacks_summary=[{"label": "core", "repo": "g/c", "ref": "main", "commit": "abc1234567"}],
        repos_summary=None,
    )
    out = (workspace / "CLAUDE.md").read_text()
    assert "My hand-written section." in out
    assert (workspace / "AGENTS.md").read_text() == out
    assert "demo" in out
