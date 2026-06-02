# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- **Colorized `-h` / `--help`** via Rich (`rich` + `rich-argparse` dependencies).
- **`--list-fields`** and **`--list-fields --all-fields`** on every fetch command to preview output columns without logging in.
- **Documentation:** [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md) for non-developers; [docs/FOR_DEVELOPERS.md](docs/FOR_DEVELOPERS.md) for codebase orientation. README is a hub with clearer paths.
- **Package rename:** PyPI distribution is now `wdt-tools` (WDT Tools — Warehouse Duct Tape). Not affiliated with HomeSource Systems the company.
- Default credentials directory: `~/credentials/wdt-tools/.env` (was `homesourcesystems`). Use `--credentials-file` if your `.env` is still in the old folder.

### Added

- PyPI packaging: `pip install wdt-tools` and console commands (`fetch-physical-inventory`, etc.).
- [PUBLISHING.md](PUBLISHING.md) and GitHub Actions workflow for PyPI releases.
- MIT [LICENSE](LICENSE).
- `homesource_common.py` — shared credentials, login handoff, Kendo parsing, and CSV/JSON output helpers.
- Unit test suite under `tests/` (pytest; no live HomeSource or Chrome in CI).
- `CONTRIBUTING.md`, `requirements-dev.txt`, `pyproject.toml`, and GitHub Actions CI workflow.
- `--version` flag on all fetch scripts (reads `VERSION`).

### Changed

- Fetch scripts print full usage with examples on `-h` / `--help` (no need to read source for basic usage).
- Fetch scripts import shared logic from `homesource_common` instead of duplicating it.
- `open_homesource.login` waits for the submit button to be clickable before clicking.
- Docstrings and README no longer reference `python-dotenv` (custom `.env` parser is used).

## [1.0.0] - 2026-06-01

### Added

- Initial public release of HomeSource export scripts.
- `fetch_physical_inventory.py` — export physical inventory runs.
- `fetch_model.py` — export model catalog records.
- `fetch_order_detail.py` — export invoiced units per order (API + closed-order HTML fallback).
- `fetch_physical_inventory_with_model.py` — inventory export joined to model metadata.
- `open_homesource.py` — Selenium login helper shared by all fetch scripts.
- Required `HOMESOURCE_BASE_URL` in credentials file (no hardcoded tenant URL).

[1.0.0]: https://github.com/YOUR_USERNAME/wdt-tools/releases/tag/v1.0.0
