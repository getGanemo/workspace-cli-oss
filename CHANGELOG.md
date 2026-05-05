# Changelog

All notable changes to `wsp` are documented here. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.4.1] — 2026-05-05

Windows ACL fix for `wsp bootstrap`. A user composing a fresh workspace on Windows had bootstrap fail at the cleanup step of `.agents/rules/` because git-cloned files were marked read-only by Windows ACL (or because an editor held a file lock). The PermissionError aborted bootstrap before product repos got cloned, leaving a half-built workspace.

### Added
- `composer._robust_rmtree()` — survives Windows ACL quirks: chmod +w retry up to N times. On final failure raises structured WSP_022 with explicit remediation.
- `wsp bootstrap --no-clean` — skip the cleanup of existing `.agents/` entirely. Escape hatch when an editor holds locks.
- New error code WSP_022 (filesystem): "Cannot clean .agents/ — file locked or permission denied".
- 6 new tests covering the rmtree paths.

### Changed
- `composer.compose_agents()` accepts a `clean` kwarg (default `True`).
- `bootstrap_action.run_bootstrap()` accepts a `clean` kwarg, plumbed from CLI flag.

## [1.4.0] — 2026-05-04

Closes the "user has v1.0.0 and doesn't know about gates added in v1.1.0+" class of bugs. Each `wsp <command>` invocation now does a best-effort daily check against GitHub Releases and warns on stderr if a newer version is available.

### Added
- `wsp/update_check.py` — best-effort daily check via `gh api repos/.../releases/latest`. Cached for 24h. Never blocks: any failure (network, auth, parse) silently swallowed.
- `--no-update-check` flag and `WSP_NO_UPDATE_CHECK=1` env var to opt out (CI, sandboxed envs, privacy).
- 9 new tests.

### Changed
- Every `wsp <command>` invocation triggers the check at startup (max once per 24h).

### Notes
- Privacy: only outbound call is to `api.github.com/repos/getGanemo/workspace-cli-oss/releases/latest` via `gh api`. No machine identifiers, no telemetry.
- Cached state in `~/.wsp/last_update_check.json` (only `checked_at` timestamp + last `latest` tag).

## [1.3.0] — 2026-05-04

Self-contained agent onboarding. Adds `awac guide quickstart` — an embedded paste-ready prompt that walks an agent through install detection, self-orientation, and workspace scaffolding without requiring the user to copy a long prompt from the docs site.

### Added
- `awac guide quickstart` — embedded one-stop prompt for a fresh agent session. The user installs the CLI once, then tells their agent to run `awac guide quickstart` and follow the output. Replaces the manual copy-paste-from-website flow as the canonical first-run path.

### Changed
- `awac guide` (no topic) listing now leads with `quickstart`.

## [1.2.1] — 2026-05-04

Third-party adoption fix. The seed READMEs that `wsp scaffold-repo` and `wsp scaffold-stack` write contained hardcoded references to `getGanemo/docs-company/governance/product-structure.md` — fine for Ganemo's internal docs, broken for any other org that adopts AWaC. Now the governance URL is overridable.

### Added
- New env var `WSP_GOVERNANCE_DOC` controls the governance URL the CLI embeds in seed READMEs and scaffold output. Default: `https://awac.ganemo.com/governance/` (the public AWaC docs site). Override with your org's own governance doc URL.
- Helper `wsp.registry.governance_doc_url()` resolves the URL via env var with fallback to the public default.

### Changed
- `wsp scaffold-repo --category <A|B|C|D|E>` seed READMEs now reference `WSP_GOVERNANCE_DOC` instead of hardcoded `getGanemo/docs-company/...`.
- `wsp scaffold-stack` seed `awac.yml` and stack README also reference `WSP_GOVERNANCE_DOC`.
- The seed `awac.yml` header now lists the configured `WSP_REGISTRY_REPO` (instead of hardcoding `getGanemo/agent-stack-core-oss`).

### Migration
- No action required for users who haven't run `scaffold-repo` / `scaffold-stack`.
- Users who run these commands and want their seed output to reference their own governance doc: set `WSP_GOVERNANCE_DOC=https://your-org.example/governance` before running.
- Output of these commands changes in v1.2.1+ (governance URL now reflects env var). Re-run on existing repos with `--update` to refresh seed text.

## [1.2.0] — 2026-05-04

Discoverability fix release. Captured during dogfooding: an agent in a fresh dir told to "set up this workspace using AWaC" searched for `awac` in PATH (not `wsp`), didn't find it, and reported the CLI as unavailable. Root cause: the binary is named `wsp` but the product is "AWaC" — agents without context don't make the connection.

### Added
- **Binary alias**: `awac` is now installed alongside `wsp` (same entry point). `pipx install` installs both. `awac --version` and `wsp --version` work identically.
- The site homepage at https://awac.ganemo.com gains a paste-ready prompt block — users copy it once into their agent and the agent installs the CLI, runs `wsp guide`, asks the right questions, and composes the workspace without inferring template from folder name.

### Changed
- `pyproject.toml#scripts` adds `awac = "wsp.cli:main"`. No code change.

### Migration
- Existing `wsp` users: nothing to do; `wsp` keeps working identically.
- Optional: rerun `pipx install --force <wheel>` to pick up the new `awac` alias.

## [1.1.0] — 2026-05-04

A workspace-as-product overlay release. Schemas `workspace/2` and `deploy/2` are introduced (alongside `awac/1` + `deploy/1`, which remain fully supported), giving workspaces a way to pin per-workspace deploy and devvault variations without forking the canonical stack metadata. Bootstrap also now materializes the product stack's metadata into `.stack/<product>/` for discoverability, and a new `wsp guide <topic>` command + a fresh-dir help banner make AWaC self-explanatory to agents that arrive without `.agents/` loaded.

### Added
- Schemas `workspace/2`, `deploy/2`, plus `lock/2`-shaped extensions:
  - `workspace.yml`: optional `deploy_overrides`, `devvault_overrides`, `product` fields. Schema enum gains `awac/2`.
  - `deploy.yml`: optional `targets_available` per component, schema enum gains `deploy/2`.
  - `workspace.lock.yml`: optional `stack_metadata` array of `{product, file, sha256, source_repo, source_commit}` entries.
- `wsp bootstrap` now materializes `.stack/<product>/{README.md, awac.yml, devvault.yml, deploy.yml}` for every stack whose `awac.yml` declares a `product`. Each file is prepended with a `SYNCED FROM` header (YAML or HTML form depending on the extension); the body hash is written to the lock so `wsp doctor` can detect drift.
- `wsp sync` re-materializes `.stack/<product>/` and refreshes the lock's `stack_metadata` (without touching cloned product repos).
- `wsp doctor` gains a `stack_metadata_drift` step that diff-hashes the workspace's `.stack/<product>/*` against the lock entries.
- `wsp deploy <product>` resolves `workspace.yml#deploy_overrides` on top of the stack's deploy.yml when run from inside a workspace dir. New `--no-overrides` flag prints raw stack defaults. Plaintext output now flags overridden components with `(workspace override applied)` and lists the changed fields.
- `wsp secrets check <product>` resolves `workspace.yml#devvault_overrides` on top of the catalog. New `--no-overrides` flag. Plaintext output marks overridden entries with `(workspace override)`.
- `wsp init` gains `--interactive`/`-i` and `--yes`/`-y` flags. Product templates (paths under `<product>/agent-stack/templates/`) now refuse to scaffold without explicit confirmation (error `WSP_020`).
- `wsp guide <topic>` — embedded guides for `init`, `onboard-product`, `deploy`, `secrets`, `discover`. `wsp guide` (no topic) lists topics. Designed for agents that arrive without `.agents/` loaded.
- `wsp migrate-deploy <product>` — upgrades a `deploy/1` spec in the cached stack repo to `deploy/2`, adding a single-element `targets_available` list per component (conservative; broaden manually before PR).
- `wsp` invoked at the root with no subcommand AND no `workspace.yml` in CWD now prints a banner pointing at `wsp guide init`, `wsp init --interactive`, and `wsp guide discover` before the standard help.
- `wsp templates --json` now exposes per-template `requires_confirmation`, `composes_stacks`, `clones_repos`, `embeds_in_product_flow`. Plaintext mode flags product templates with a `[product]` marker.
- New error codes: `WSP_018` (overrides require schema awac/2), `WSP_019` (override target not in `targets_available`), `WSP_020` (product template without confirmation), `WSP_021` (stack metadata drift).

### Changed
- `__schema__` is now `awac/2`. The CLI accepts both `awac/1` and `awac/2` manifests (overrides require `awac/2`).
- Bootstrap and sync write `schema: awac/2` to the lock when `stack_metadata` is non-empty; otherwise stay at `awac/1` for backwards compat.
- Plaintext `wsp bootstrap` output now appends a `stack metadata materialized:` block listing materialized files plus suggested next-step commands (`wsp secrets check`, `wsp deploy`).
- `wsp deploy` schema validation accepts both `deploy/1` and `deploy/2`.

### Migration
- Existing `awac/1` workspaces: no action required. Continue working unchanged.
- To use deploy/devvault overrides in a workspace: bump the manifest's `schema: awac/1` to `schema: awac/2` and add `deploy_overrides:` / `devvault_overrides:` blocks. Re-run `wsp bootstrap`.
- To upgrade a product's deploy.yml to v2: run `wsp migrate-deploy <product>`, review the patched file, and PR it back to the canonical `<product>/agent-stack` repo.
- After bumping `wsp` to 1.1.0, run `wsp bootstrap` once in each existing workspace whose stack publishes a `product` — this materializes `.stack/<product>/` so `wsp doctor` can track drift.

### Internal
- 27 new tests across 7 new files. Total: 84/84 passing.

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

[Unreleased]: https://github.com/getGanemo/workspace-cli-oss/compare/v1.4.1...HEAD
[1.4.1]: https://github.com/getGanemo/workspace-cli-oss/compare/v1.4.0...v1.4.1
[1.4.0]: https://github.com/getGanemo/workspace-cli-oss/compare/v1.3.0...v1.4.0
[1.3.0]: https://github.com/getGanemo/workspace-cli-oss/compare/v1.2.1...v1.3.0
[1.2.1]: https://github.com/getGanemo/workspace-cli-oss/compare/v1.2.0...v1.2.1
[1.2.0]: https://github.com/getGanemo/workspace-cli-oss/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/getGanemo/workspace-cli-oss/compare/v1.0.0...v1.1.0
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
