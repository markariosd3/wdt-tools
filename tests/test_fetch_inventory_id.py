from __future__ import annotations

import fetch_inventory_id as fii


def test_default_fields_include_requested_inventory_columns():
    assert "timestamp_utc" in fii.DEFAULT_FIELDS
    assert "ProductId_FK" in fii.DEFAULT_FIELDS
    assert "ModelNumber" in fii.DEFAULT_FIELDS
    assert "is_allocated" in fii.DEFAULT_FIELDS


def test_flatten_query_formats_item_tags_and_purchase_order_item():
    rows = [
        {
            "InventoryId": "123",
            "purchase_order_item": {"unit_cost": 4.56},
            "item_tags": [{"value": "red"}, {"value": "blue"}],
        }
    ]

    flat = fii.flatten_query(rows, "123", "2026-06-22T00:00:00Z")

    assert flat[0]["purchase_order_item.unit_cost"] == 4.56
    assert flat[0]["item_tags.value"] == "[red, blue]"
    assert flat[0]["_source_query"] == "123"
    assert flat[0]["_error"] == ""
    assert flat[0]["timestamp_utc"] == "2026-06-22T00:00:00Z"


def test_flatten_query_reads_tags_value_key_and_brackets_output():
    rows = [
        {
            "InventoryId": "25494",
            "tags": [
                {
                    "InventoryTagId": 6,
                    "Value": "D-DISPLAY",
                    "created_at": "2023-02-17T22:33:20.000000Z",
                },
                {
                    "InventoryTagId": 7,
                    "Value": "CLEARANCE",
                },
            ],
        }
    ]

    flat = fii.flatten_query(rows, "25494", "2026-06-22T00:00:00Z")

    assert flat[0]["item_tags.value"] == "[D-DISPLAY, CLEARANCE]"
