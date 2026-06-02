# Contributing

Thank you for improving **WDT Tools**. This document is for people changing the code.

- **End users** → [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md)
- **New developers** → [docs/FOR_DEVELOPERS.md](docs/FOR_DEVELOPERS.md)

Below: machine setup, tests, and pull request expectations.

## Prerequisites

- **Python 3.10+**
- **Google Chrome** (only needed when running fetch scripts against a real tenant — not for unit tests)
- Git

## One-time setup

```bash
git clone https://github.com/YOUR_USERNAME/wdt-tools.git
cd wdt-tools

python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

pip install -r requirements-dev.txt
```

`requirements-dev.txt` installs runtime dependencies plus **pytest** and **ruff**.

## PyPI releases

Maintainers publish to PyPI using [PUBLISHING.md](PUBLISHING.md). Version lives in
`VERSION`; console commands are declared in `pyproject.toml` under
`[project.scripts]`.

## Command-line help

Each fetch script documents itself via `-h` or `--help` (examples, credentials, exit codes):

```bash
python fetch_physical_inventory.py -h
```

## Running tests (required before you commit)

Unit tests use **no** HomeSource credentials, **no** Chrome, and **no** network calls.

```bash
# Full suite
pytest

# Verbose
pytest -v

# One file
pytest tests/test_homesource_common.py
```

All tests must pass before you open a pull request or push to `main`.

## Linting

```bash
ruff check .
```

CI runs `ruff check` and `pytest` on Python 3.10 and 3.12 for every push and pull request.

## Project layout

| Path | Role |
|------|------|
| `homesource_common.py` | Shared credentials, login handoff, flattening, I/O helpers |
| `open_homesource.py` | Selenium login page automation |
| `fetch_*.py` | CLI entry points (thin wrappers around domain logic) |
| `tests/` | Offline unit tests and JSON/HTML fixtures |
| `.github/workflows/ci.yml` | Automated checks on GitHub |

Import shared logic from `homesource_common` instead of copying it into another fetch script.

## Credentials (for manual / integration runs only)

Tests do **not** read your `.env` file. To run exports against a real tenant:

1. Create `%USERPROFILE%\credentials\wdt-tools\.env` (Windows) or `~/credentials/wdt-tools/.env` (macOS/Linux).
2. Set `APP_USERNAME`, `APP_PASSWORD`, and `HOMESOURCE_BASE_URL`.
3. Run a script, e.g. `python fetch_physical_inventory.py --run-ids 641`.

Never commit `.env` files or export files that contain customer or cost data.

## Integration tests (optional, local only)

There are no live integration tests in CI. If you add tests that call HomeSource:

- Mark them `@pytest.mark.integration`
- Run with `pytest -m integration` only when you intend to hit a real tenant
- Do not add secrets to the repository

## Changing output columns (semver)

Default CSV columns are part of the **public contract** documented in the README. If you add, remove, or rename default columns:

1. Update the script’s `DEFAULT_FIELDS` or `COLUMNS`
2. Update README and CHANGELOG
3. Bump **MINOR** (new optional columns) or **MAJOR** (breaking changes) per [Semantic Versioning](https://semver.org/)
4. Update or add tests under `tests/` that assert the column list

## Pull request checklist

- [ ] `pytest` passes locally
- [ ] `ruff check .` passes locally
- [ ] README / CHANGELOG updated if behavior or CLI changed
- [ ] No credentials or customer data in the diff
