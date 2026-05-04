# wsp — Agent Workspace as Code

> **AWaC** (Agent Workspace as Code): declare your AI-agent workspace once. Compose it from versioned stack repos. Get the same `.agents/`, the same `CLAUDE.md`, the same tooling on every machine.

`wsp` is the reference CLI for [Agent Workspace as Code (AWaC)](https://gist.github.com/GanemoCorp/fdc1042067615003e8aa4a8406198a61). It composes an agent workspace declaratively from versioned stack repos so that every developer (and every AI coding agent) gets the same rules, skills, and workflows — no copy-paste, no drift, no bloat.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Releases](https://img.shields.io/github/v/release/getGanemo/workspace-cli-oss)](https://github.com/getGanemo/workspace-cli-oss/releases)

---

## Why AWaC

Anyone using AI coding agents seriously hits two walls:

- **Drift**: rules and skills get tweaked per-project, copied across repos, and stop matching each other within weeks.
- **Bloat**: every project needs the same MCP setup, AWS safety rules, deploy patterns — but copy-pasting them turns every `.agents/` into a 200-file mess no one owns.

AWaC borrows from Infrastructure as Code: a declarative manifest (`workspace.yml`), versioned stacks (one repo per topic), a CLI that resolves and composes them deterministically.

```yaml
# workspace.yml
schema: workspace/1
name: my-feature
stacks:
  - core           # universal rules + the shortcut registry
  - aws            # cloud safety patterns
  - mcp            # MCP server bootstrapping
  - <product>/agent-stack    # your project's stack
```

Run `wsp bootstrap`, get `.agents/{rules,skills,workflows}/` composed in deterministic order, your product repos cloned, your `CLAUDE.md` and `AGENTS.md` generated. Lockfile records exact commits. Idempotent.

## Install

Requirements: Python ≥ 3.10, `git`, `pipx`, and `gh` (GitHub CLI logged in via `gh auth login` — required at runtime to clone stack repos).

### Quickstart (recommended)

Each release attaches a wheel to a [GitHub Release](https://github.com/getGanemo/workspace-cli-oss/releases):

```bash
TAG=$(gh release view --repo getGanemo/workspace-cli-oss --json tagName -q .tagName)
gh release download "$TAG" --repo getGanemo/workspace-cli-oss --pattern '*.whl' --dir /tmp/wsp
pipx install /tmp/wsp/wsp-*.whl
wsp --version
wsp doctor
```

Upgrade later by repeating with the new tag and `pipx install --force`.

### Dev install (working on `wsp` itself)

```bash
git clone https://github.com/getGanemo/workspace-cli-oss ~/dev/workspace-cli
pipx install -e ~/dev/workspace-cli
wsp --version
wsp doctor
```

## Use it

```bash
mkdir my-feature && cd my-feature
wsp init my-feature --template blank
wsp bootstrap
```

After `bootstrap`:

- `.agents/{rules,skills,workflows}/` is composed from the active stacks.
- `CLAUDE.md` (canonical) and `AGENTS.md` (mirror) are generated at the workspace root.
- Product repos declared by the stacks are cloned into the workspace.
- `workspace.lock.yml` records the exact commits resolved.

Commit `workspace.yml` and `workspace.lock.yml` to your repo. The `.agents/` folder is composed on demand — every contributor runs `wsp bootstrap` once and gets the same workspace.

## Commands

| Command | What it does |
|---|---|
| `wsp init <name> [--template <id>]` | Scaffold a new workspace from a registry template. |
| `wsp bootstrap [--update-locks]` | Resolve, clone, and compose. Idempotent. |
| `wsp sync` | Refresh stacks and recompose `.agents/`. Does not touch product repos. |
| `wsp status` | Read-only diff between `workspace.lock.yml` and current state. |
| `wsp scaffold-stack <org>` | Introspect a GitHub org and seed `<org>/agent-stack`. |
| `wsp scaffold-repo <full> --category <A|B|C|D|E>` | Create or audit a product-repo README. |
| `wsp deploy <product>` | Plan-only deploy validator (reads `deploy.yml` spec). |
| `wsp secrets check <product>` | Resolve secret catalog + per-machine vault, report missing entries. |
| `wsp audit <product>` | Audit governance + AWaC alignment for a product. |
| `wsp governance check` | Compare local `awac.yml#org_scaffold` mirror against governance source. |
| `wsp templates` / `wsp shortcuts` | List registry templates / stack shortcuts. |
| `wsp doctor` | Diagnose environment (git, gh, registry, cache, devvault, governance). |
| `wsp schema <workspace|awac|lock|deploy|devvault>` | Print the canonical JSON Schema. |
| `wsp --agent-manifest` | Machine-readable command catalog (for AI agents). |

All commands accept `--json` for structured output. Errors carry `code`, `category`, `cause`, and `remediation` fields so AI agents can react programmatically.

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `WSP_REGISTRY_REPO` | `getGanemo/agent-stack-core-oss` | Where the canonical `awac.yml` registry lives. |
| `WSP_REGISTRY_BRANCH` | `main` | Branch of the registry repo. |
| `WSP_CACHE_DIR` | `~/.wsp/cache` | Where stacks and repos are cloned. |

You can point `WSP_REGISTRY_REPO` to your own fork or your team's private registry. The schemas are stable; the registry contents are yours to define.

## Philosophy

- **Agent-first, not human-first**: every command emits machine-readable output. Errors are codes, not paragraphs. Agents can drive the CLI without breaking.
- **Composition over duplication**: stacks override each other in declared order. Adding a rule means adding it to one stack, not to N projects.
- **Declarative + reproducible**: `workspace.yml` is the source of truth. The lockfile makes it deterministic across machines and time.
- **Local-only**: no SaaS, no telemetry, no backend. The CLI is 100% local; stacks live in plain GitHub repos. You own everything.
- **Permissive license**: MIT. Fork it, vendor it, embed it in your tooling. AWaC is methodology + reference impl, not a lock-in.

## Documentation

- **Specification (canonical gist)**: <https://gist.github.com/GanemoCorp/fdc1042067615003e8aa4a8406198a61>
- **Full docs site**: <https://github.com/getGanemo/awac-docs> (or the dedicated docs domain — see the awac-docs repo for the live URL).
- **CHANGELOG**: [CHANGELOG.md](CHANGELOG.md)

## Stacks

Public reference stacks (composed by `wsp bootstrap` when listed in your `workspace.yml`):

- [`getGanemo/agent-stack-core-oss`](https://github.com/getGanemo/agent-stack-core-oss) — universal foundation: registry of shortcuts, templates, governance mirror, universal rules and skills.
- [`getGanemo/agent-stack-aws-oss`](https://github.com/getGanemo/agent-stack-aws-oss) — AWS safety + deploy patterns.
- [`getGanemo/agent-stack-mcp-oss`](https://github.com/getGanemo/agent-stack-mcp-oss) — MCP server bootstrap conventions.
- [`getGanemo/agent-stack-cloudflare-oss`](https://github.com/getGanemo/agent-stack-cloudflare-oss) — Cloudflare Pages / Workers patterns.
- [`getGanemo/agent-stack-research-oss`](https://github.com/getGanemo/agent-stack-research-oss) — research/branding/thesis templates.

You can also publish your own stacks. Anything that exposes `awac.yml` + `.agents/` + (optional) `templates/` is a valid stack.

## Contributing

PRs welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for dev setup, conventions, and what we're looking for.

For security issues, see [SECURITY.md](SECURITY.md) — please **do not** open public issues.

This project follows the [Contributor Covenant 2.1](CODE_OF_CONDUCT.md). Be excellent to each other.

## Acknowledgements

AWaC was created by [Fernando Pastor](https://github.com/GanemoCorp) at [Ganemo Corp](https://www.ganemo.com), where it composes the workspaces of every agent-driven SaaS we ship (Acme, Widget, Atlas, Cobalt, Delta). The design was deeply informed by working day-to-day with [Anthropic Claude](https://www.anthropic.com/claude) and the broader AI coding ecosystem (Cursor, Aider, Continue).

## License

MIT. See [LICENSE](LICENSE).
