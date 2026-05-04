# Guide: onboard-product — bring a new Ganemo product into AWaC

The path:

- A "product" in Ganemo is a vertical (Acme, Widget, Atlas, ...) with its own GitHub org and an `<org>/agent-stack` repo that publishes the product's deploy/devvault/template metadata.
- Onboarding creates the org's agent-stack from governance, registers it in `getGanemo/agent-stack-core-oss/awac.yml` (shortcut + template entries), and audits the result.
- The full workflow is multi-step and may include creating Cat A repos before scaffold-stack runs.
- After onboarding you can `wsp init <name> --template <product>-feature --yes` to create workspaces against the new product.

Relevant `wsp` commands:

- `wsp scaffold-stack <org>` — introspect the org and create `<org>/agent-stack` from governance. Uses `--push-direct` during onboarding.
- `wsp scaffold-repo <org>/<repo> --category <A|B|C|D|E>` — create or audit a Cat A/B/C/D/E repo's README to governance convention.
- `wsp audit <product>` — verify the product is fully aligned with governance + AWaC convention (Cat A repos exist with the right descriptions, agent-stack carries `awac.yml`/`devvault.yml`/`deploy.yml`/templates, registry has shortcut + template).
- `wsp governance check` — verify the governance↔awac.yml mirror.

Full canonical workflow: `getGanemo/agent-stack-core-oss/workflows/onboard_new_product.md`.
