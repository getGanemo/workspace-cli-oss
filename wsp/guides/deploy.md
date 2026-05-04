# Guide: deploy — how the deploy router + workspace overrides work

The path:

- Each product owns a `<product>/agent-stack/deploy.yml` (schema `deploy/2`) that lists components, each pinned to a target (odoo_sh, aws_ecs, aws_lambda, aws_ec2_ssm, cloudflare_pages, cloudflare_workers, github_pages, manual).
- The CLI's `wsp deploy <product>` is plan-only: it parses + validates + presents the resolved plan. Actual execution is workflow-driven (`getGanemo/agent-stack-core-oss/workflows/deploy_product.md`).
- Workspaces can override per-component fields via `workspace.yml#deploy_overrides` (requires schema `awac/2`). The CLI merges stack defaults with workspace overrides — workspace wins per field. Arrays REPLACE entirely, target objects merge field-by-field.
- A component with `targets_available` declared restricts which targets a workspace may swap to. Trying to override outside that list raises `WSP_019`.
- Setting `skip: true` on a component in `deploy_overrides` removes it from the plan (annotated as `(skipped per workspace override)` in plaintext output).

Relevant `wsp` commands:

- `wsp deploy <product>` — show the resolved plan (with overrides applied).
- `wsp deploy <product> --no-overrides` — show raw stack defaults.
- `wsp deploy <product> --component <name>` — filter to one component.
- `wsp deploy <product> --json` — machine-readable output.
- `wsp migrate-deploy <product>` — upgrade a v1 spec to v2 with conservative `targets_available` lists.
- `wsp schema deploy` — print the JSON schema.

Full canonical workflow: `getGanemo/agent-stack-core-oss/workflows/deploy_product.md`.
