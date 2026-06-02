"""Tests for --list-fields column preview."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize(
    "script,expected_column",
    [
        ("fetch_physical_inventory.py", "ModelNumber"),
        ("fetch_model.py", "NetAvailable"),
        ("fetch_order_detail.py", "InventoryId"),
        ("fetch_physical_inventory_with_model.py", "manufacturer.Name"),
    ],
)
def test_list_fields_default(script: str, expected_column: str):
    result = subprocess.run(
        [sys.executable, str(ROOT / script), "--list-fields"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"},
    )
    assert result.returncode == 0, result.stderr
    assert expected_column in result.stdout
    assert "Default columns" in result.stdout or "default" in result.stdout.lower()


def test_list_fields_all_fields_inventory():
    result = subprocess.run(
        [sys.executable, str(ROOT / "fetch_physical_inventory.py"),
         "--list-fields", "--all-fields"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"},
    )
    assert result.returncode == 0, result.stderr
    assert "--all-fields mode" in result.stdout


def test_order_detail_all_fields_lists_full_schema():
    result = subprocess.run(
        [sys.executable, str(ROOT / "fetch_order_detail.py"),
         "--list-fields", "--all-fields"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"},
    )
    assert result.returncode == 0, result.stderr
    assert "_source_order_id" in result.stdout
    assert "MFGSerialNumber" in result.stdout
