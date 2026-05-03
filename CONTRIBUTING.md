# Contributing to wsp / AWaC

Thanks for your interest in contributing. AWaC (Agent Workspace as Code) is an open methodology + CLI for composing AI-agent workspaces declaratively. This document covers how to get a dev environment running, what we accept, and how to file good PRs.

## Quickstart for contributors

```bash
git clone https://github.com/getGanemo/workspace-cli-oss
cd workspace-cli
python -m venv .venv && source .venv/bin/activate    # macOS/Linux
# .venv\Scripts\activate                              # Windows PowerShell
pip install -e ".[dev]"
pytest -q
```

You should see all tests passing. If anything fails out of the gate on a clean checkout, **that's the first issue worth filing**.

## Requirements

- Python ≥ 3.10
- `git` ≥ 2.30
- `gh` (GitHub CLI) authenticated via `gh auth login` — needed at runtime to clone stack repos. Tests don't require it.
- `pipx` (recommended) for end-user-style installs.

## What we want

- **Bug fixes** for crashes, wrong error messages, or behavior that doesn't match the docs.
- **New stack templates** under `tests/fixtures/` plus end-to-end tests.
- **More agent-friendly diagnostics** — clearer error codes, better remediation strings, more `--json` coverage.
- **Cross-platform fixes** for Windows / macOS / Linux paths and shell behaviors.
- **Documentation improvements** — both in this repo and the docs site.

## What we don't want (without discussing first)

- Breaking changes to the `awac/1` or `workspace/1` schemas without an ADR.
- Adding heavyweight dependencies (rule of thumb: stdlib + click + pyyaml + jsonschema is the budget).
- Interactive wizards or TTY prompts in the core commands. AWaC is agent-first; commands stay scriptable.
- New top-level commands without a use case grounded in real workspaces.

When in doubt, **open an issue first** describing the change and its motivation. We'll triage quickly.

## Development workflow

1. Fork the repo and create a branch from `main`. Keep branches focused on one change.
2. Run `pytest -q` after every change. CI will block PRs with failing tests.
3. Use `pipx install -e .` to test your local copy as if it were installed.
4. Run `wsp doctor` in a scratch workspace to validate your change end-to-end.
5. Update `CHANGELOG.md` under the `## Unreleased` section.
6. Open a PR using the template. Link the issue if there is one.

### Commit style

- Subject line ≤ 70 chars, imperative mood (`add scaffold-stack flag`, not `Added flag`).
- Body explains the *why*, not the *what*.
- Reference issues in the body (`Closes #42`).

### Tests

We use `pytest` with simple unit tests. Conventions:

- One test file per module (`test_<module>.py`).
- Fixtures under `tests/fixtures/`.
- Avoid network in unit tests; mock `subprocess` calls when needed.
- End-to-end validation lives in manual `wsp` runs; we don't have a CI integration suite yet.

## Filing issues

Use the [issue templates](.github/ISSUE_TEMPLATE/). For bugs, include:

- `wsp --version`
- Python version, OS
- The exact `wsp` command that failed
- Full output (use `--json` if available)
- The relevant section of your `workspace.yml`

For feature requests, focus on the underlying problem you're trying to solve before proposing a specific design.

## Security issues

Do **not** open public issues for security vulnerabilities. See [SECURITY.md](SECURITY.md) for the disclosure process.

## Code of Conduct

This project follows the [Contributor Covenant 2.1](CODE_OF_CONDUCT.md). Be excellent to each other.

## License

By contributing, you agree your contributions will be licensed under the [MIT License](LICENSE) that covers this project.
