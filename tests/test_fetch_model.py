"""Tests for fetch_model (offline)."""

from __future__ import annotations

import json
from urllib.parse import unquote

import fetch_model as fm


def test_build_filter_exact():
    f = fm.build_filter("ABC", contains=False, only_with_obsolete_onhand=False)
    assert f["logic"] == "and"
    assert f["filters"][0]["field"] == "ModelNumber"
    assert f["filters"][0]["operator"] == "eq"
    assert f["filters"][0]["value"] == "ABC"


def test_build_filter_contains_or_group():
    f = fm.build_filter("VBW", contains=True, only_with_obsolete_onhand=False)
    assert f["logic"] == "or"
    assert len(f["filters"]) == 3


def test_build_filter_obsolete_restriction():
    f = fm.build_filter("X", contains=False, only_with_obsolete_onhand=True)
    assert f["logic"] == "and"
    assert any(x.get("field") == "ObsoleteOnHand" for x in f["filters"])


def test_showall_url_embeds_filter():
    url = fm._showall_url(
        "https://tenant.example.com",
        "M1",
        contains=False,
        only_with_obsolete_onhand=False,
        take=200,
        skip=0,
        page_size=200,
    )
    blob = json.loads(unquote(url.split("?", 1)[1]))
    assert blob["take"] == 200
    assert blob["pageSize"] == 200


def test_flatten_query_provenance():
    rows = fm.flatten_query([{"ModelNumber": "Z"}], "Z")
    assert rows[0]["_source_query"] == "Z"
    assert rows[0]["ModelNumber"] == "Z"


def test_default_fields_contract():
    assert fm.DEFAULT_FIELDS[0] == "_source_query"
    assert "manufacturer.Name" in fm.DEFAULT_FIELDS
