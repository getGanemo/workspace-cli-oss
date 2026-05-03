"""Unit tests for the governance comparator. Pure compare() function, no I/O."""

from __future__ import annotations

from wsp.governance import compare


GOOD_DOC = """
## Categorías de repositorios

### Categoría A — Gobierno y operaciones (obligatorios siempre)

| Repo | Función |
|---|---|
| `project_management` | text |
| `agent-stack` | text |
| `infrastructure` | text |

### Categoría B — Superficie pública

| Repo | Función |
|---|---|
| `web` | text |
| `docs` | text |
| `docs-users` | text |
| `docs-developers` | text |

### Categoría C — Código de producto

**Nunca** usar nombres genéricos sin información (`code`, `app`, `src`, `main`).

### Categoría D — Componentes opcionales

| Repo | Función |
|---|---|
| `mcp-server` | text |
| `terraform-modules` | text |
| `<framework>-starter` | text |
| `<componente>-build` | text |

### Categoría E — Integraciones cross-organización

text
"""


GOOD_AWAC = {
    "org_scaffold": {
        "category_a_governance": {
            "repos": [
                {"name": "project_management"},
                {"name": "agent-stack"},
                {"name": "infrastructure"},
            ],
        },
        "category_b_public_surface": {
            "repos": [
                {"name": "web"}, {"name": "docs"},
                {"name": "docs-users"}, {"name": "docs-developers"},
            ],
        },
        "category_c_product_code": {
            "naming_rules": {"forbidden_names": ["code", "app", "src", "main"]},
        },
        "category_d_optional": {
            "repos": [
                {"name": "mcp-server"},
                {"name": "terraform-modules"},
                {"glob": "*-starter"},
                {"glob": "*-build"},
            ],
        },
        "category_e_cross_org": {"odoo_modules": {}},
        "excluded_names": [
            ".github", "agent-stack", "infrastructure", "project_management",
            "docs", "docs-users", "docs-developers", "web",
        ],
    },
}


def test_aligned_returns_no_problems():
    assert compare(GOOD_AWAC, GOOD_DOC) == []


def test_missing_cat_a_repo_in_awac_is_detected():
    awac = {"org_scaffold": dict(GOOD_AWAC["org_scaffold"])}
    awac["org_scaffold"]["category_a_governance"] = {
        "repos": [{"name": "project_management"}, {"name": "agent-stack"}],
    }
    problems = compare(awac, GOOD_DOC)
    assert any("infrastructure" in p and "Cat A" in p for p in problems)


def test_forbidden_names_mismatch_is_detected():
    awac = {"org_scaffold": dict(GOOD_AWAC["org_scaffold"])}
    awac["org_scaffold"]["category_c_product_code"] = {
        "naming_rules": {"forbidden_names": ["code", "app"]},
    }
    problems = compare(awac, GOOD_DOC)
    assert any("forbidden Cat C names" in p for p in problems)


def test_missing_glob_pattern_is_detected():
    awac = {"org_scaffold": dict(GOOD_AWAC["org_scaffold"])}
    awac["org_scaffold"]["category_d_optional"] = {
        "repos": [{"name": "mcp-server"}, {"glob": "*-starter"}],
    }
    problems = compare(awac, GOOD_DOC)
    assert any("Cat D" in p and "*-build" in p for p in problems) \
        or any("Cat D" in p and "terraform-modules" in p for p in problems)


def test_missing_excluded_names_is_detected():
    awac = {"org_scaffold": dict(GOOD_AWAC["org_scaffold"])}
    awac["org_scaffold"]["excluded_names"] = [
        ".github", "agent-stack", "infrastructure", "project_management",
        "docs", "web",
        # docs-users / docs-developers missing
    ]
    problems = compare(awac, GOOD_DOC)
    assert any("excluded names" in p.lower() for p in problems)


def test_no_org_scaffold_is_a_problem():
    problems = compare({}, GOOD_DOC)
    assert problems and "org_scaffold" in problems[0]
