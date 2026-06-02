"""Verify fetch scripts print usage and examples on -h / --help."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

FETCH_SCRIPTS = [
    ("fetch_physical_inventory.py", "fetch-physical-inventory"),
    ("fetch_model.py", "fetch-model"),
    ("fetch_order_detail.py", "fetch-order-detail"),
    ("fetch_physical_inventory_with_model.py", "fetch-physical-inventory-with-model"),
]


@pytest.mark.parametrize("script,prog_name", FETCH_SCRIPTS)
@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_help_includes_examples(script: str, prog_name: str, flag: str):
    path = ROOT / script
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    result = subprocess.run(
        [sys.executable, str(path), flag],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert "Examples:" in out
    assert "exit codes:" in out
    assert "credentials:" in out
    assert prog_name in out
