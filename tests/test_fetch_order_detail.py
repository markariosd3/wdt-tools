"""Tests for fetch_order_detail (offline)."""

from __future__ import annotations

import json
from pathlib import Path

import fetch_order_detail as fod

FIXTURES = Path(__file__).parent / "fixtures"


def test_flatten_order_one_unit():
    data = json.loads((FIXTURES / "order_minimal.json").read_text(encoding="utf-8"))
    rows = fod.flatten_order(data, "17667")
    assert len(rows) == 1
    row = rows[0]
    assert row["_source_order_id"] == "17667"
    assert row["_source"] == "api"
    assert row["Model"] == "TEST-MODEL"
    assert row["InventoryId"] == "INV-1"
    assert row["MFGSerialNumber"] == "SN-99"


def test_flatten_order_misc_line_without_units():
    data = {
        "invoice_items": [
            {
                "OrderItemId": 1,
                "Model": "DELIVERY",
                "invoiced_inventory": [],
            }
        ]
    }
    rows = fod.flatten_order(data, "1")
    assert len(rows) == 1
    assert rows[0]["Model"] == "DELIVERY"
    assert rows[0]["InventoryId"] == ""


def test_invoice_row_from_cells():
    field_to_idx = {
        "Manufacturer": 1,
        "Model": 2,
        "Description": 3,
        "Qty": 7,
    }
    cells = ["", "GE", "ABC123", "Fridge", "", "", "", "2"]
    row = fod.invoice_row_from_cells("999", field_to_idx, cells)
    assert row["_source"] == "invoice_html"
    assert row["_source_order_id"] == "999"
    assert row["Manufacturer"] == "GE"
    assert row["Model"] == "ABC123"
    assert row["Qty"] == "2"
    assert row["InventoryId"] == ""


def test_columns_contract_provenance_first():
    assert fod.COLUMNS[:3] == ["_source_order_id", "_source", "_error"]


def test_load_skip_set_csv(tmp_path):
    out = tmp_path / "prior.csv"
    out.write_text(
        "_source_order_id,_source,Model\n1,api,A\n2,api,B\n",
        encoding="utf-8",
    )
    assert fod.load_skip_set(str(out)) == {"1", "2"}
