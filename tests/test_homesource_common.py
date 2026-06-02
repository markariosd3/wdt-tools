"""Unit tests for homesource_common (no network, no Chrome)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import homesource_common as hc


def test_read_project_version():
    assert hc.read_project_version() == "1.0.0"


def test_load_credentials_success(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text(
        "APP_USERNAME=u\nAPP_PASSWORD=p\nHOMESOURCE_BASE_URL=https://t.example.com\n",
        encoding="utf-8",
    )
    creds = hc.load_credentials(str(env))
    assert creds["APP_USERNAME"] == "u"
    assert creds["HOMESOURCE_BASE_URL"] == "https://t.example.com"


def test_load_credentials_missing_file(tmp_path: Path):
    with pytest.raises(hc.CredentialsError, match="not found"):
        hc.load_credentials(str(tmp_path / "missing.env"))


def test_load_credentials_missing_keys(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text("APP_USERNAME=only\n", encoding="utf-8")
    with pytest.raises(hc.CredentialsError, match="missing required"):
        hc.load_credentials(str(env))


def test_load_credentials_strips_quotes_and_bom(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_bytes(
        b"\xef\xbb\xbfAPP_USERNAME=\"user\"\n"
        b"APP_PASSWORD='pass'\n"
        b"HOMESOURCE_BASE_URL=https://t.example.com\n"
    )
    creds = hc.load_credentials(str(env))
    assert creds["APP_USERNAME"] == "user"
    assert creds["APP_PASSWORD"] == "pass"


def test_flatten_record_nested_and_list():
    obj = {
        "ModelNumber": "X",
        "manufacturer": {"Name": "Acme"},
        "tags": [1, 2],
        "empty": None,
    }
    flat = hc.flatten_record(obj)
    assert flat["ModelNumber"] == "X"
    assert flat["manufacturer.Name"] == "Acme"
    assert json.loads(flat["tags"]) == [1, 2]
    assert flat["empty"] == ""


@pytest.mark.parametrize(
    "payload,expected_rows,expected_total",
    [
        ([{"a": 1}], 1, None),
        ({"data": [{"a": 1}], "total": 5}, 1, 5),
        ({"Data": [{"b": 2}], "Total": "3"}, 1, 3),
        ({"solo": True}, 1, None),
        ("not-a-dict", 0, None),
    ],
)
def test_extract_kendo_rows(payload, expected_rows, expected_total):
    rows, total = hc.extract_kendo_rows(payload)
    assert len(rows) == expected_rows
    assert total == expected_total


def test_detect_format():
    assert hc.detect_format("out.json", None) == "json"
    assert hc.detect_format("out.csv", None) == "csv"
    assert hc.detect_format(None, "json") == "json"


def test_dedupe_preserves_order():
    assert hc.dedupe(["2", "1", "2", "3", "1"]) == ["2", "1", "3"]


def test_load_ids_inline_and_csv(tmp_path: Path):
    assert hc.load_ids_from_input(
        None, "csv", "OrderId", "1, 2 ,1",
        json_key_candidates=("OrderId",),
    ) == ["1", "2"]

    csv_file = tmp_path / "orders.csv"
    csv_file.write_text("OrderId\n10\n20\n", encoding="utf-8")
    assert hc.load_ids_from_input(
        str(csv_file), "csv", "OrderId", None,
        json_key_candidates=("OrderId",),
    ) == ["10", "20"]


def test_load_ids_json_array(tmp_path: Path):
    j = tmp_path / "runs.json"
    j.write_text('[{"PhysicalInventoryRunId": 641}, 642]', encoding="utf-8")
    ids = hc.load_ids_from_input(
        str(j), "json", "PhysicalInventoryRunId", None,
        json_key_candidates=("PhysicalInventoryRunId", "RunId"),
    )
    assert ids == ["641", "642"]


def test_emit_curated_columns_order():
    rows = [{"_source_run_id": "1", "ModelNumber": "A", "_error": ""}]
    cols = hc.build_curated_columns(
        rows,
        ["_source_run_id", "_error"],
        ["_source_run_id", "ModelNumber"],
        quiet=True,
    )
    assert cols == ["_source_run_id", "ModelNumber", "_error"]
