"""Unit tests for `wsp scaffold-stack`. Pure-function tests; network paths are
exercised via integration in the live workspace, not here."""

from __future__ import annotations

from pathlib import Path

import pytest

from wsp import scaffold_stack_action as ss
from wsp.scaffold_stack_action import (
    OdooModuleRef,
    RepoFacts,
    classify_repos,
    discover_odoo_modules,
    org_to_product,
    write_seed,
)


ORG_SCAFFOLD = {
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
    "category_e_cross_org": {
        "odoo_modules": {"org": "erp-partners"},
    },
    "excluded_names": [".github", "agent-stack"],
}


def test_org_to_product_strips_get_prefix():
    assert org_to_product("getGanemo") == "ganemo"
    assert org_to_product("getAtlas") == "atlas"
    assert org_to_product("getCobalt") == "cobalt"
    assert org_to_product("Delta") == "delta"
    assert org_to_product("acme") == "acme"
    assert org_to_product("widget") == "widget"


def _facts(name: str, **kw) -> RepoFacts:
    return RepoFacts(
        name=name,
        description=kw.get("description", ""),
        default_branch=kw.get("default_branch", "main"),
        visibility=kw.get("visibility", "PRIVATE"),
    )


def test_classify_handles_all_five_categories():
    repos = [
        _facts("project_management"),
        _facts("agent-stack"),
        _facts("infrastructure"),
        _facts("docs"),
        _facts("web"),
        _facts("platform"),
        _facts("orchestrator"),
        _facts("mcp-server"),
        _facts("delta-nextjs-starter"),
        _facts("openclaw-build"),
        _facts("code"),  # forbidden Cat C name
        _facts(".github"),  # genuinely excluded
    ]
    classified, excluded = classify_repos(repos, ORG_SCAFFOLD)
    by_cat = {}
    for c in classified:
        by_cat.setdefault(c.category, []).append(c.facts.name)

    assert set(by_cat.get("A", [])) == {"project_management", "agent-stack", "infrastructure"}
    assert set(by_cat.get("B", [])) == {"docs", "web"}
    assert set(by_cat.get("C", [])) == {"platform", "orchestrator"}
    assert set(by_cat.get("D", [])) == {"mcp-server", "delta-nextjs-starter", "openclaw-build"}
    assert "code" in by_cat.get("unclassified", [])
    # `.github` is genuinely excluded — does not appear at all.
    all_names = {c.facts.name for c in classified}
    assert ".github" not in all_names
    assert "agent-stack" in {n for n in excluded}


def test_discover_odoo_modules_by_name_prefix_and_description():
    erp_partners = [
        _facts("widget_saas", description="Widget SaaS commercial module for Odoo 19"),
        _facts("widget_core", description="Widget core module"),
        _facts("acme_portal", description="Customer portal for Acme"),
        _facts("unrelated_module", description="Some other thing"),
        _facts("agent-stack", description="agent stack"),
    ]
    widget_mods = discover_odoo_modules("widget", erp_partners)
    assert {m.name for m in widget_mods} == {"widget_saas", "widget_core"}

    acme_mods = discover_odoo_modules("acme", erp_partners)
    assert {m.name for m in acme_mods} == {"acme_portal"}

    # Not detected: unrelated
    other = discover_odoo_modules("atlas", erp_partners)
    assert other == []


def test_write_seed_creates_full_layout(tmp_path: Path):
    classified = [
        ss.ClassifiedRepo(facts=_facts("project_management"), category="A", reason="governance"),
        ss.ClassifiedRepo(facts=_facts("docs"), category="B", reason="public surface"),
        ss.ClassifiedRepo(facts=_facts("platform"), category="C", reason="product code"),
    ]
    odoo = [OdooModuleRef(name="delta_demo", branch_default="19-dev", path="addons/delta_demo/")]
    write_seed(tmp_path, "Delta", "delta", classified, odoo, cat_a_blank=False)

    assert (tmp_path / "awac.yml").exists()
    assert (tmp_path / "templates/feature.yml").exists()
    assert (tmp_path / "README.md").exists()
    for sub in ("rules", "skills", "workflows"):
        assert (tmp_path / sub).is_dir()

    awac = (tmp_path / "awac.yml").read_text()
    assert "product: delta" in awac
    assert "name: project_management" in awac
    assert "name: docs" in awac
    assert "name: platform" in awac
    assert "delta_demo" in awac
    assert 'org:  erp-partners' in awac

    feat = (tmp_path / "templates/feature.yml").read_text()
    assert "stacks:" in feat
    assert "- core" in feat
    assert "- delta" in feat
    # has Cat E so erp-partners stack is appended
    assert "- erp-partners" in feat


def test_write_seed_blank_cat_a_for_lazy_org(tmp_path: Path):
    write_seed(tmp_path, "cobalt-org", "cobalt", classified=[], odoo_modules=[], cat_a_blank=True)
    awac = (tmp_path / "awac.yml").read_text()
    assert "scaffold inicial" in awac
    assert "cobalt" in awac.lower()


def test_merge_existing_awac_replaces_only_repos_block():
    existing = (
        "### header\n"
        "product: x\n"
        "scope: x-saas\n"
        "\n"
        "repos:\n"
        "  - name: old1\n"
        "    branch_default: main\n"
        "  - name: old2\n"
        "    branch_default: main\n"
        "\n"
        "trailing_key: keep_me\n"
    )
    new_block = (
        "repos:\n"
        "  - name: new1\n"
        "    branch_default: main\n"
    )
    merged = ss._merge_existing_awac(existing, new_block)
    assert "old1" not in merged
    assert "old2" not in merged
    assert "new1" in merged
    assert "trailing_key: keep_me" in merged
    assert "product: x" in merged
