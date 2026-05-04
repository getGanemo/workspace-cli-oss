# Guide: secrets — how devvault works

The path:

- Each product publishes a `devvault.yml` catalog (schema `devvault/1`) at `<product>/agent-stack/devvault.yml`. It maps logical secret names to relative paths under the per-machine vault.
- The vault location is per-machine: `~/.devvault/.config.yml#vault_path`. Catalogs MUST NOT include `vault_path`.
- A workspace can redirect logical names to alternate sub-paths via `workspace.yml#devvault_overrides` (requires schema `awac/2`). Useful for staging variants or a developer-local sandbox vault.
- `wsp secrets check <product>` is read-only: it confirms each logical secret resolves to an existing, readable file. It NEVER prints secret values.

Relevant `wsp` commands:

- `wsp secrets check <product>` — verify all secrets resolve, with overrides applied.
- `wsp secrets check <product> --no-overrides` — same check using raw catalog paths.
- `wsp secrets check <product> --json` — machine-readable output.
- `wsp doctor` — includes the `devvault_config` step.
- `wsp schema devvault` — print the JSON schema.

Canonical rule for agents using secrets: `getGanemo/agent-stack-core-oss/rules/use_devvault.md`.
