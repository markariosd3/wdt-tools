"""Packaging metadata and entry points (offline)."""

from __future__ import annotations

from pathlib import Path

import tomllib

import fetch_model
import fetch_order_detail
import fetch_physical_inventory
import fetch_physical_inventory_with_model

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"


def _pyproject() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def test_pyproject_declares_package_name():
    project = _pyproject()["project"]
    assert project["name"] == "wdt-tools"
    assert project["requires-python"] == ">=3.10"


def test_console_scripts_declared_in_pyproject():
    scripts = _pyproject()["project"]["scripts"]
    assert scripts["fetch-physical-inventory"] == "fetch_physical_inventory:cli"
    assert scripts["fetch-model"] == "fetch_model:cli"
    assert scripts["fetch-order-detail"] == "fetch_order_detail:cli"
    assert (
        scripts["fetch-physical-inventory-with-model"]
        == "fetch_physical_inventory_with_model:cli"
    )


def test_version_file_matches_pyproject_dynamic():
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert version
    dynamic = _pyproject()["tool"]["setuptools"]["dynamic"]
    assert dynamic["version"]["file"] == "VERSION"


def test_cli_callables():
    for mod in (
        fetch_physical_inventory,
        fetch_model,
        fetch_order_detail,
        fetch_physical_inventory_with_model,
    ):
        assert callable(mod.cli)
