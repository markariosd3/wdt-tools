"""Tests for fetch_physical_inventory (offline)."""

from __future__ import annotations

from urllib.parse import unquote

import fetch_physical_inventory as fpi


def test_showall_url_without_paging():
    url = fpi._showall_url("https://tenant.example.com", "641")
    assert url.startswith("https://tenant.example.com/inventory/physical/active/showAll?")
    payload = unquote(url.split("?", 1)[1])
    assert '"PhysicalInventoryRunId":"641"' in payload


def test_showall_url_with_paging():
    url = fpi._showall_url("https://tenant.example.com", "641", take=500, skip=500)
    assert "take=500" in url
    assert "skip=500" in url


def test_flatten_run_stamps_provenance():
    rows = fpi.flatten_run([{"InventoryId": 1, "nested": {"x": 1}}], "99")
    assert len(rows) == 1
    assert rows[0]["_source_run_id"] == "99"
    assert rows[0]["_error"] == ""
    assert rows[0]["InventoryId"] == 1


def test_default_fields_contract():
    """Curated column list is part of the public CLI contract (semver)."""
    assert fpi.DEFAULT_FIELDS[0] == "_source_run_id"
    assert "ModelNumber" in fpi.DEFAULT_FIELDS
    assert "InventoryId" in fpi.DEFAULT_FIELDS
