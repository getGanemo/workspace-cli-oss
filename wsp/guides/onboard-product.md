# Guide: onboard-product — bring a NEW product into AWaC end-to-end (public OSS edition)

> Run `awac guide onboard-product` and feed the output to your agent. The agent reads the 9-step plan, asks you the 5 inputs upfront, runs `awac scaffold-stack`, creates the 3 Cat A repos, registers the product in the core registry, scaffolds project_management, sets up the devvault catalog, audits the result, and bootstraps a first workspace — all in one continuous flow. Wall-clock: 15-30 min.

---

You are an AI coding agent helping me onboard a NEW product into AWaC.

This is the path "I have the GitHub org + the AWS account + the domain
ready; bring this product into AWaC". It's NOT the path "I have an
existing product, compose a workspace from a feature template" (that's
`awac guide quickstart` for an existing-product workspace).

The canonical workflow lives at:
  https://raw.githubusercontent.com/getGanemo/agent-stack-core/main/workflows/onboard_new_product.md

That workflow has 9 steps. This guide gives you everything you need to
run them without reading the canonical file (in case `gh` raw fetch is
unavailable).

---

## Step 0 — Collect the 5 inputs upfront. Do NOT improvise

Ask the user for these 5 values BEFORE doing anything. Show them as a
list and confirm all at once. Do not invent placeholders for missing
values; if any is missing, stop and ask.

| Input | Example | Notes |
|---|---|---|
| Display name | `Secrevo` | Capitalized as the user wants it shown. |
| Slug | `secrevo` | lowercase, no spaces, no `get` prefix. |
| GitHub org | `getsecrevo` | Convention: if the slug is taken on GitHub, prefix `get`. The CLI strips `get` to derive the slug. |
| Domain | `secrevo.com` | The product's primary domain. Used in the `infrastructure` Cat A repo's description. |
| AWS account ID | `123456789012` | 12 digits. Used in the `infrastructure` description. If pending, ask the user to create the AWS account first — do NOT use a placeholder. |
| Workspace local path | `~/dev/secrevo-bootstrap/` | Empty directory where the first workspace will live. |

Once confirmed, do not ask again unless the user changes one explicitly.

---

## Step 1 — Verify CLI + auth + org visibility

```bash
awac --version 2>&1 || echo "WSP_MISSING"        # need 1.5.0+
gh auth status >/dev/null 2>&1 || echo "GH_AUTH_MISSING"
gh api orgs/<ORG> >/dev/null 2>&1 || echo "ORG_NOT_VISIBLE"
```

- `wsp` not installed or below 1.5.0 → `pipx install --force <wheel>` from
  the latest `getGanemo/workspace-cli-oss` release. (Private repo. `gh` must
  be authenticated against the GitHub account that owns the org first.)
- `gh` not authenticated → `gh auth login --web --hostname github.com`.
- Org not visible → user has to create it on GitHub OR add permissions to
  the PAT / GitHub App. Stop and tell the user.
- All OK → proceed.

---

## Step 2 — Show the plan, get explicit user confirmation, THEN scaffold-stack

Before any GitHub-mutating call, print the plan and wait for an explicit
"OK ejecutá" (or equivalent) from the user. Do NOT proceed with `--yes`
flags on your own.

The plan to show:

```
About to onboard product '<slug>' into AWaC. This will:

1. Run `awac scaffold-stack <ORG>` which:
   - Introspects the org (currently has 0 repos).
   - Creates <ORG>/agent-stack (private repo) with seed awac.yml.
   - Auto-registers `<slug>: <ORG>/agent-stack` and template
     `<slug>-feature` in getGanemo/agent-stack-core/awac.yml.

2. Create 3 Cat A repos (private) with governance-compliant READMEs:
   - <ORG>/project_management
   - <ORG>/infrastructure  (description includes AWS account + domain)
   - <ORG>/agent-stack  (already created in step 1)

3. Refresh <ORG>/agent-stack to declare the 3 Cat A repos.

4. Initialize project_management with a first progreso.md
   following manage_project_state convention.

5. Add devvault.yml catalog to <ORG>/agent-stack with a minimum set of
   secrets (aws, cloudflare). Suggest others based on convention.

6. Add an audit entry in getGanemo/docs-company governance.

7. Run `awac audit <slug>` and report 11/11 PASS or list what's missing.

8. Bootstrap a first workspace in <local-path> using template
   `<slug>-feature`.

9. Run `awac secrets check <slug>` and report which secrets need to be
   populated in ~/.devvault/<slug>/.
```

Wait for the user's literal confirmation in this turn before continuing.

---

## Step 3 — Execute Step 2 of the canonical workflow: scaffold-stack

```bash
awac scaffold-stack <ORG>
```

Verify the output contains:
- `pushed: yes (main)`
- `registry: ok — <slug> registered in getGanemo/agent-stack-core`

If `registry: skipped/no-op` → the auto-register flag was off. Re-run
with default (no flags) to register.

---

## Step 4 — Create the 3 Cat A repos

```bash
awac scaffold-repo <ORG>/project_management --category A
awac scaffold-repo <ORG>/infrastructure --category A \
  --aws-account <AWS_ID> --domain <DOMAIN>
# agent-stack already exists from Step 3, no scaffold-repo needed.
```

The seed READMEs are governance-compliant. Each repo is created PRIVATE
by default. Do not push public.

---

## Step 5 — Refresh agent-stack to declare the 3 Cat A repos

```bash
awac scaffold-stack <ORG> --update --push-direct
```

`--push-direct` skips the PR review (the user is the org owner; the
change is additive). Verifies the awac.yml#repos block now lists
project_management + infrastructure + agent-stack.

---

## Step 6 — Initialize project_management/progreso.md

Clone the just-created project_management locally, add a first
`progreso.md` per the `manage_project_state` skill convention:

```
# Progreso — <ProductDisplayName>

## Estado actual (YYYY-MM-DD)
- Producto onboardeado en AWaC.
- agent-stack registrado en getGanemo/agent-stack-core.
- 3 repos Cat A creados.

## Pendiente
- Scaffold Cat C/D repos del producto cuando exista código.
- Crear primer workspace de feature con `awac init`.
```

Push to main of `<ORG>/project_management`.

---

## Step 7 — Author devvault.yml catalog in agent-stack

Edit `<ORG>/agent-stack/devvault.yml` to declare the minimum secrets:

```yaml
schema: devvault/1
product: <slug>
description: >
  Secrets needed to operate <ProductDisplayName>.
  Resolves against ~/.devvault/<vault_path>/ on the developer's machine.
secrets:
  aws_account: aws/account.yml
  aws: aws/<slug>.yml
  cloudflare: providers/cloudflare.yml
```

Suggest additions based on the product's nature (e.g. stripe if SaaS
billing, openai if LLM, smtp if email product). Ask the user before
adding any.

Push to main.

---

## Step 8 — Add audit entry in your governance repo

If your organization keeps a governance doc (the URL set via
`WSP_GOVERNANCE_DOC`), append a row for the new product there. The path
is up to your conventions — typical layout is `governance/products.md`
with a table per product.

**How to do the edit without polluting the workspace**:
- Preferred: use `gh api -X PUT repos/<your-org>/<your-docs-repo>/contents/governance/products.md`
  with the SHA of the existing file + base64-encoded patched content.
  Commits directly without a local clone.
- If you must clone, clone to `/tmp/<random>/`, edit, push, delete.
- DO NOT `git clone` the docs repo inside the workspace dir — it leaves
  a stale repo subfolder confusing the developer.

Skip this step entirely if your org doesn't track products in a governance
doc yet — `awac audit` does NOT require it.

Then verify:

```bash
awac governance check
```

Should report aligned. If divergence, re-read both sides and reconcile.

---

## Step 9 — Audit, bootstrap workspace, validate secrets

```bash
awac audit <slug>           # must report 11/11 PASS
cd <local-workspace-path>
awac init <slug>-feature --template <slug>-feature --yes
cd <slug>-feature
awac bootstrap
awac secrets check <slug>   # report which secrets need population
```

The `--yes` here is justified: the user explicitly confirmed onboarding
in Step 2 of this guide. If the user did not confirm, stop here and ask.

Report at the end:
- Audit result (must be PASS).
- Bootstrap result (file count, .agents/ tree, .stack/<slug>/ contents,
  cloned repos).
- Missing secrets the user needs to populate from password manager
  (1Password, Bitwarden, etc.).

---

## Anti-patterns (do NOT do these)

- **Auto-pass `--yes` without explicit user confirmation in this turn**.
  The Step 2 plan exists exactly to catch this. The CLI gates also fire
  (WSP_020) but the discipline is yours.
- **Invent an AWS account ID or domain because the user didn't say**.
  Stop and ask. A wrong account ID gets baked into the `infrastructure`
  Cat A description and is a chore to fix later.
- **Skip `awac audit` at the end**. The audit is the canonical "did
  onboarding succeed" check. Don't trust your own narrative; trust
  `audit <slug>` returning 11/11.
- **Push public the new Cat A repos**. They start private by default;
  promotion to public is a deliberate later decision.
- **Edit your registry's `awac.yml` manually instead of via
  scaffold-stack auto-register**. The CLI does it idempotently. Set
  `WSP_REGISTRY_REPO` if your registry isn't the default.
- **`git clone <docs-repo>` inside the workspace dir** during Step 8.
  The clone leaves a stale repo subfolder polluting the workspace. Use
  `gh api` direct, or clone to /tmp.
- **Edit `.stack/<slug>/{devvault,deploy}.yml` in the workspace** to
  silence a missing-secret error. Edit canonical in `<ORG>/agent-stack`
  + `awac sync` instead.

---

## Recovery: a Step failed mid-workflow

- `scaffold-stack` failed → most likely `gh` auth issue or org not
  visible. Re-run after fixing.
- `scaffold-repo` failed for one Cat A repo → re-run only that one;
  others are independent.
- `audit` reports failures → read each FAIL entry; the remediation
  field tells you what's missing. Most common: forgot the registry
  auto-register, or didn't add devvault.yml.
- Wrong AWS account in `infrastructure` description → run `awac
  scaffold-repo <ORG>/infrastructure --category A --update
  --aws-account <CORRECT_ID> --domain <DOMAIN>` to open a PR fixing it.

---

## Cross-references

- Canonical workflow (in your registry): `<your-registry>/workflows/onboard_new_product.md`
- Skill: `manage_project_state` (used in Step 6 for progreso.md format).
- Rule: `aws_resource_safety` (cross-product safety while you have AWS open).
- Site: https://awac.ganemo.com
