# For developers — how WDT Tools works

This page explains **why** the project is shaped the way it is. End users should
start with [GETTING_STARTED.md](GETTING_STARTED.md) instead.

---

## What problem we solve

HomeSource exposes rich data in the browser (Kendo grids, order APIs, invoice
pages). Operators often need that data in **Excel** or downstream systems.
WDT Tools automates:

1. **Login** (Selenium + Chrome, once per run).
2. **HTTP fetch** (reuse session cookies—fast, no clicking).
3. **Flatten + CSV/JSON** (stable columns, `_error` rows for partial failure).

The name **Warehouse Duct Tape** reflects scope: small, sharp CLI scripts that
stick existing UI/API surfaces together—not a full integration platform.

---

## Architecture (one picture)

```text
  .env credentials
        │
        ▼
  open_homesource.login()  ──►  Chrome (headless or visible)
        │
        ▼
  homesource_common.build_authenticated_session()
        │
        ├──► requests.Session  ──►  JSON APIs (inventory, model, open orders)
        │
        └──► WebDriver (kept for fetch_order_detail closed orders only)
                    └──► scrape invoice HTML table

  fetch_*.py main()  ──►  loop IDs  ──►  emit CSV/JSON
```

---

## Repository map

| File | Role |
|------|------|
| `homesource_common.py` | Credentials, login handoff, Kendo parsing, CSV/JSON output, shared `--help` footer |
| `open_homesource.py` | Selenium login form only |
| `fetch_physical_inventory.py` | Physical inventory `showAll` endpoint + paging |
| `fetch_model.py` | Model grid search + paging |
| `fetch_order_detail.py` | Order API + closed-order HTML fallback |
| `fetch_physical_inventory_with_model.py` | Composes inventory + model lookup in **one** session |
| `tests/` | Offline unit tests (no live tenant) |

**Rule:** put reusable logic in `homesource_common`; keep each `fetch_*.py` as a
thin CLI wrapper.

---

## Authentication details

- Success signal: leave `/login` and receive cookie `laravel_session`
  (`LOGIN_SESSION_COOKIE_NAME` in `homesource_common`).
- Session cookies are copied into `requests.Session` for API calls.
- `fetch_order_detail` keeps the driver alive to render closed-order invoice pages.
- Other scripts quit Chrome immediately after login.

---

## Output contract

- **stderr** — progress and errors.
- **stdout** or `-o` — tabular data.
- **Exit codes** — `0` all OK, `1` partial failures (`_error` column), `2` fatal.
- Default columns are **curated**; `--all-fields` exposes full API shape (semver:
  changing defaults is a MINOR/MAJOR event—see README versioning).

---

## Running from source

```bash
git clone https://github.com/YOUR_USERNAME/wdt-tools.git
cd wdt-tools
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements-dev.txt
pytest
ruff check .
```

Editable install:

```bash
pip install -e ".[dev]"
```

Console entry points are declared in `pyproject.toml` `[project.scripts]`.

---

## Testing philosophy

Tests never hit HomeSource or Chrome. They cover:

- Pure helpers (`flatten_record`, `extract_kendo_rows`, `.env` parsing).
- Order flattening and invoice row mapping (fixtures).
- Packaging metadata and `--help` output.

Optional future: `@pytest.mark.integration` behind env vars (local only).

---

## Publishing

See [PUBLISHING.md](../PUBLISHING.md). PyPI distribution name: **`wdt-tools`**.

---

## Related docs

- [README.md](../README.md) — reference (flags, columns, troubleshooting).
- [CONTRIBUTING.md](../CONTRIBUTING.md) — PR checklist, CI.
- [CHANGELOG.md](../CHANGELOG.md) — release notes.
