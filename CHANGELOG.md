# Changelog

All notable changes to `wsp` are documented here. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] — 2026-05-03

### First public release

The 1.0 cut of `wsp`. Cumulative scope from the 0.x line, now under MIT license, with public reference stacks (`getGanemo/agent-stack-{core,aws,mcp,cloudflare,research}-oss`), a public docs site (`getGanemo/awac-docs`), a Welcome / Roadmap / Contribute set of pinned issues, and Discussions enabled.

### Highlights vs 0.9.0
- Repository made public (was private during the 0.x line).
- License: MIT (was "Proprietary").
- Documentation moved to a dedicated public repo and Astro Starlight site.
- README rewritten with hero + value prop + commands + philosophy + acknowledgements.
- `CHANGELOG.md`, `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md` added.
- Issue templates (bug / feature / question) + PR template added.
- Branch protection on `main`: forbid force pushes + deletions, require linear history.

### What is in 1.0 (cumulative)
- Commands: `init`, `bootstrap`, `sync`, `status`, `scaffold-stack`, `scaffold-repo`, `deploy`, `secrets check`, `audit`, `governance check`, `templates`, `shortcuts`, `doctor`, `schema`, `--agent-manifest`.
- Schemas: `workspace/1`, `awac/1`, `lock/1`, `deploy/1`, `devvault/1` — all stable.
- Public reference stacks: 5 transversal (core, aws, mcp, cloudflare, research).
- Distribution via GitHub Releases (PyPI on the roadmap — see ADR 012).
- Tests: 56/56 passing.

### What is *not* in 1.0
- `wsp promote` (propagating workspace changes back to source stack).
- `wsp worktree` (companion to `git worktree`).
- PyPI distribution.
- IDE-side bootstrapping.
- See the [Roadmap](https://github.com/getGanemo/workspace-cli-oss/issues/2).

## [0.9.0] — 2026-05-03

### Added
- `wsp scaffold-stack --update --push-direct` — push refresh straight to `main` instead of opening a PR. Useful when the user owns the agent-stack and the change is additive (e.g. after creating Cat A repos during product onboarding). Default without the flag remains PR mode (safe for third-party / sensitive repos).

### Changed
- Workflow `onboard_new_product` Step 4 now uses `--push-direct`, so onboarding runs uninterrupted between Step 2 and Step 9.

## [0.8.0] — 2026-05-03

### Added
- `wsp audit <product>` — read-only audit against governance + AWaC. 11 checks covering Cat A repos, descriptions, agent-stack assets (`awac.yml`, `devvault.yml`, `deploy.yml`, templates), registry shortcut + template entries.
- `wsp scaffold-stack` now auto-registers the new shortcut and template entry in `agent-stack-core/awac.yml` (commit direct to main, idempotent). Opt out with `--no-register`.
- `wsp scaffold-repo --aws-account <ID> --domain <DOM>` — Cat A repo descriptions now follow the governance `description_pattern` (`project_management`, `agent-stack`, `infrastructure` each with their specific form).

### Internal
- 8 new tests. Total: 56/56 passing.

## [0.7.0] — 2026-05-03

### Added
- `wsp deploy <product> [--component <name>]` — plan-only validator + presenter. Resolves the deploy spec from the registry cache, validates against `deploy/1`, prints components, targets, `pre_steps`, and promotions. Execution is workflow-driven (`deploy_product` router), not CLI-driven, by design.
- `wsp secrets check <product>` — resolves the secret catalog + per-machine vault config and reports per-entry exists/readable. Read-only; never prints values.

## [0.6.0] — 2026-05-03

### Added
- Schemas `deploy/1` and `devvault/1`. Exposed via `wsp schema deploy` and `wsp schema devvault`.
- `wsp doctor` — new `devvault_config` step that verifies `~/.devvault/.config.yml` and resolves the configured `vault_path`.

## [0.5.0] — 2026-05-03

### Added
- `wsp scaffold-repo <full> --category <A|B|C|D|E> [--update] [--no-push]` — per-category README templates plus an audit checklist. The new-repo path creates the GitHub repo and pushes the seed README. The `--update` path audits a live README and opens a PR appending missing required sections while preserving existing content.

## [0.4.0] — 2026-05-03

### Changed
- Governance mirror check moved from a GitHub Actions workflow to the local CLI. New command `wsp governance check` clones `docs-company` via `gh` credentials and compares it against `awac.yml#org_scaffold`. The same check is also run as a step inside `wsp doctor`. Removes the need for a PAT/workflow secret.

### Removed
- The original GitHub Actions workflow + standalone script in `agent-stack-core` (commit `808a495`).

## [0.3.0] — 2026-05-03

### Added
- `wsp scaffold-stack <org> [--update] [--no-push] [--branch]` — introspects a GitHub org, classifies its repos into Categories A–E, and seeds `<org>/agent-stack` from governance. `--update` opens a PR; default is direct push to the new repo's `main`.

## [0.2.0] — 2026-05-03

### Added
- `wsp sync` — refresh stacks only (does NOT re-clone product repos).
- `wsp status` — read-only diff between `workspace.lock.yml` and the current state. Reports `stacks`, `repos`, `agents_drift` separately.

## [0.1.0] — 2026-05-02

Initial pilot release. CLI `wsp` is `pipx`-installable.

### Commands shipped
- `wsp init <name> [--template <id>] [--target <path>]`
- `wsp bootstrap [--update-locks]`
- `wsp templates` / `wsp shortcuts`
- `wsp doctor`
- `wsp schema <workspace|awac|lock>`
- `wsp --agent-manifest`

### End-to-end
- `wsp init my-feature --template <product>-feature && wsp bootstrap` clones the declared stacks plus the product repos and composes `.agents/` deterministically.
- Lockfile is generated, idempotent. Hand-edited blocks under `.agents/` are preserved.

[Unreleased]: https://github.com/getGanemo/workspace-cli-oss/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/getGanemo/workspace-cli-oss/compare/v0.9.0...v1.0.0
[0.9.0]: https://github.com/getGanemo/workspace-cli-oss/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/getGanemo/workspace-cli-oss/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/getGanemo/workspace-cli-oss/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/getGanemo/workspace-cli-oss/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/getGanemo/workspace-cli-oss/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/getGanemo/workspace-cli-oss/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/getGanemo/workspace-cli-oss/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/getGanemo/workspace-cli-oss/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/getGanemo/workspace-cli-oss/releases/tag/v0.1.0
