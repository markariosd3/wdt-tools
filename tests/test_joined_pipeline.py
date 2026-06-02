"""Contract tests for the joined inventory+model pipeline."""

from __future__ import annotations

import fetch_physical_inventory_with_model as joined


def test_model_append_fields_contract():
    assert joined.MODEL_APPEND_FIELDS == [
        "manufacturer.Name",
        "category.Name",
        "ShortDescription",
        "Color",
    ]


def test_append_model_fields_blank_and_sentinel():
    rows = [
        {"ModelNumber": "A"},
        {"ModelNumber": "B"},
        {"ModelNumber": ""},
    ]
    lookup = {
        "A": {f: "x" for f in joined.MODEL_APPEND_FIELDS},
        "B": {f: joined.MULTIPLE_MATCH_SENTINEL for f in joined.MODEL_APPEND_FIELDS},
    }
    joined.append_model_fields(rows, lookup)
    assert rows[0]["ShortDescription"] == "x"
    assert rows[1]["Color"] == joined.MULTIPLE_MATCH_SENTINEL
    assert rows[2]["Color"] == ""
