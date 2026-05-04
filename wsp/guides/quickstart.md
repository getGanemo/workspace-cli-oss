# Guide: quickstart — paste-ready agent prompt for a fresh AWaC workspace

> Run `awac guide quickstart` to print this. Pipe it into your agent's chat as a single message — the agent reads it as instructions and walks the user through the entire setup.

---

You are an AI coding agent. Set up an AWaC workspace in this folder.

AWaC ("Agent Workspace as Code") is a Terraform-style tool: a `workspace.yml`
manifest declares which versioned "stack" repos compose into this
workspace's `.agents/` folder + `CLAUDE.md` + `AGENTS.md`. The CLI binary
is named `wsp` (also installed as `awac` from v1.2.0+). Public repo:
https://github.com/getGanemo/workspace-cli-oss — site:
https://awac.ganemo.com

Required CLI version: 1.2.0 or later.

Step 1 — Detect CLI state (DO NOT install or upgrade yet, just probe):
    awac --version 2>/dev/null || python -m wsp --version 2>/dev/null \
      || echo "NOT_INSTALLED"

  Three branches:
    a) Already installed AND version >= 1.2.0 → SKIP to Step 2.
    b) Installed but outdated → upgrade with:
         gh release download --repo getGanemo/workspace-cli-oss \
           --pattern '*.whl' --dir /tmp/wsp
         pipx install --force /tmp/wsp/wsp-*.whl
       Then continue to Step 2.
    c) NOT_INSTALLED → install with:
         gh release download --repo getGanemo/workspace-cli-oss \
           --pattern '*.whl' --dir /tmp/wsp
         pipx install /tmp/wsp/wsp-*.whl
       (If `gh` is unavailable, fall back to `pip install <wheel-url>` from
       https://github.com/getGanemo/workspace-cli-oss/releases/latest)
       Then continue to Step 2.

Step 2 — Self-orient. Run BEFORE doing anything else:
    awac guide discover
    awac guide init
    awac templates --json

Step 3 — Ask me, do not infer:
    - The workspace name (kebab-case lowercase, no leading digit).
    - Which template I want. Read the templates from `awac templates --json`
      and show me which are "product templates" (flagged
      `requires_confirmation: true` — those clone product repos and embed
      this workspace in a product-specific deploy/secrets flow).
    - DO NOT infer the template from the folder name. Folder prefixes are
      coincidence; templates carry semantic blast radius. If unclear,
      default to `blank`.

Step 4 — Once I confirm name + template:
    awac init <name> --template <T>     # add --yes only if template is
                                         # product-specific AND I confirmed
                                         # in this turn
    cd <name>
    awac bootstrap

Step 5 — If template was product-specific, after bootstrap run:
    awac secrets check <product>        # validates my local vault
    awac deploy <product>               # plan-only

Step 6 — Report what got created (file count, .agents/ tree summary, any
missing secrets, deploy plan summary) and stop. Do not start writing
product code unless I ask for it.

Rules:
- The CLI emits structured JSON errors. Parse `code` + `remediation` and
  follow the remediation; do not improvise around errors.
- Never edit files under `.stack/<product>/` directly — that's a read-only
  mirror of the product stack. For per-workspace variation, edit
  `workspace.yml#deploy_overrides` or `#devvault_overrides`.
- Never push or commit anything I haven't asked for.
- If your org has its own governance doc, set
  `WSP_GOVERNANCE_DOC=<url>` before running scaffold-repo / scaffold-stack
  so seed READMEs reference it instead of the AWaC public default.
