"""Unit tests for `wsp scaffold-repo`. Pure-function tests; network paths
are exercised live in integration."""

from __future__ import annotations

import pytest

from wsp import scaffold_repo_action as sr
from wsp.scaffold_repo_action import (
    CATEGORY_SPECS,
    audit_readme,
    patch_existing_readme,
)


def test_audit_no_readme_fails():
    a = audit_readme(None, "C")
    assert a.has_readme is False
    assert a.too_short is True
    assert a.passes is False
    assert "Purpose" in a.missing_required


def test_audit_full_template_passes():
    spec = CATEGORY_SPECS["C"]
    text = spec.template_fn("acme/orchestrator", "acme", "orchestrator")
    a = audit_readme(text, "C")
    assert a.has_readme is True
    assert a.too_short is False
    assert a.missing_required == []
    assert a.passes is True


def test_audit_missing_required_section_fails():
    text = (
        "# repo\n\n"
        "## Purpose\n\nLorem ipsum dolor sit amet consectetur. " * 10
    )
    a = audit_readme(text, "C")
    assert a.passes is False
    assert "Stack" in a.missing_required
    assert "Tests" in a.missing_required
    assert "Cross-references" in a.missing_required


def test_audit_short_readme_fails_even_with_headings():
    text = "# x\n## Purpose\n## Stack\n## Architecture role\n"
    a = audit_readme(text, "C")
    assert a.too_short is True
    assert a.passes is False


def test_patch_appends_missing_sections_to_existing_readme():
    existing = (
        "# acme/orchestrator\n\n"
        "Backend service. " * 30 + "\n\n"
        "## Purpose\n\nDoes things.\n\n"
        "## Stack\n\nFastAPI + Postgres.\n"
    )
    patched = patch_existing_readme(existing, "C", "acme/orchestrator", "acme", "orchestrator")
    assert patched is not None
    assert "Architecture role" in patched
    assert "Primary consumers" in patched
    assert "Tests" in patched
    # Original content preserved
    assert "FastAPI + Postgres." in patched
    assert "Backend service." in patched
    # Re-auditing the patched content shows all required sections present.
    a = audit_readme(patched, "C")
    assert a.missing_required == []


def test_patch_returns_none_when_already_passing():
    spec = CATEGORY_SPECS["A"]
    text = spec.template_fn("acme/infrastructure", "acme", "infrastructure")
    assert patch_existing_readme(text, "A", "acme/infrastructure", "acme", "infrastructure") is None


def test_each_template_satisfies_its_own_audit():
    for cat, spec in CATEGORY_SPECS.items():
        text = spec.template_fn("foo/bar", "foo", "bar")
        a = audit_readme(text, cat)
        assert a.passes, f"category {cat} template fails its own audit: missing {a.missing_required}"


def test_categories_are_exact():
    assert sr.CATEGORIES == ("A", "B", "C", "D", "E")
    assert set(CATEGORY_SPECS.keys()) == set(sr.CATEGORIES)


def test_governance_description_for_infrastructure_with_aws_and_domain():
    desc = sr._governance_description(
        "A", "infrastructure", "secrevo",
        aws_account="123456789012", domain="secrevo.com",
    )
    assert "Secrevo" in desc and "Terraform" in desc
    assert "AWS account 123456789012" in desc
    assert "Cloudflare secrevo.com" in desc


def test_governance_description_for_infrastructure_with_placeholders_when_missing():
    desc = sr._governance_description("A", "infrastructure", "secrevo")
    assert "<AWS_ACCOUNT_ID>" in desc
    assert "secrevo.com" in desc  # default placeholder


def test_governance_description_for_project_management():
    desc = sr._governance_description("A", "project_management", "atlas")
    assert "internal project management" in desc
    assert "Atlas" in desc


def test_governance_description_for_agent_stack():
    desc = sr._governance_description("A", "agent-stack", "acme")
    assert "Agent stack" in desc and "Acme" in desc


def test_governance_description_falls_back_for_non_cat_a():
    desc = sr._governance_description("C", "platform", "acme")
    assert "C" in desc and "acme" in desc
