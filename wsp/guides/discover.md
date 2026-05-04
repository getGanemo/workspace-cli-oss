# Guide: discover — for an agent in a fresh workspace with no .agents/

The situation:

- You are an agent dropped in a directory and asked to do work. There is no `.agents/` so you have no rules, no skills, no workflows loaded automatically.
- You can still bootstrap your understanding of AWaC from the `wsp` CLI itself.

The path:

1. Run `wsp --version` to confirm `wsp` is installed (target: 0.10.x or newer).
2. Run `ls workspace.yml 2>/dev/null` to determine if this is a workspace at all. If absent, you are in an empty dir — see `wsp guide init`.
3. If `workspace.yml` exists, run `wsp doctor` to verify the local environment (git, gh, devvault, governance mirror, stack metadata drift).
4. Run `wsp status` to see how the lockfile compares to the current tree (which stacks/repos drifted).
5. If `.stack/<product>/` exists, that is the materialized stack metadata (read-only mirror of the canonical files in the stack repo). Inspect `.stack/<product>/awac.yml` and `.stack/<product>/deploy.yml` to learn the product structure.
6. Run `wsp deploy <product>` and `wsp secrets check <product>` (read-only) to understand the deploy/secrets contract for this workspace.
7. To get the full agent context, run `wsp bootstrap` — this materializes `.agents/{rules,skills,workflows}/` from the active stacks. After that, follow your normal agent loop with the rules loaded.

Relevant `wsp` commands:

- `wsp guide init` / `wsp guide deploy` / `wsp guide secrets` — topic-specific guides.
- `wsp templates --json` — to understand what templates exist.
- `wsp shortcuts` — to understand which stacks the registry knows.
- `wsp --agent-manifest` — machine-readable command catalog.
