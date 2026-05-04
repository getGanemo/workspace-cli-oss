# Guide: init — scaffolding a new AWaC workspace

The path:

- A workspace is a directory containing a `workspace.yml` plus, after `wsp bootstrap`, cloned product repos and a composed `.agents/` tree.
- `wsp init` writes only the `workspace.yml`. Cloning and composition happen at `wsp bootstrap` time.
- Templates live in stack repos (e.g. `getGanemo/agent-stack-core-oss/templates/blank.yml`, `atlas-org/agent-stack/templates/feature.yml`).
- Templates that target a Ganemo product (under `<product>/agent-stack/templates/`) clone that product's repos and embed your workspace in the product's deploy/secrets flows. They REQUIRE explicit confirmation (`--yes` or `--interactive`).
- Workspace name must be kebab-case lowercase ASCII, no leading digit (e.g. `my-feature`).
- After init, you should:
  1. Inspect the generated `workspace.yml` and adjust if needed.
  2. Run `wsp bootstrap` to clone repos + materialize stack metadata into `.stack/<product>/`.
  3. Run `wsp doctor` to verify env (git, gh, devvault).

Relevant `wsp` commands:

- `wsp templates --json` — list all templates with their requires_confirmation, composes_stacks, clones_repos.
- `wsp init <name>` — quick non-interactive scaffold (default template `blank`).
- `wsp init <name> --template <name>` — pick a template explicitly. Product templates need `--yes`.
- `wsp init --interactive` — pick template + workspace name interactively.
- `wsp bootstrap` — clone + compose the workspace.
- `wsp guide discover` — for an agent dropped into a fresh workspace with no `.agents/`.

Full canonical workflow: `getGanemo/agent-stack-core-oss/workflows/init_workspace.md`.
