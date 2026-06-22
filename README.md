# WDT Tools (`wdt-tools`)

[![Version](https://img.shields.io/badge/version-1.0.0-blue)](VERSION)
[![SemVer](https://img.shields.io/badge/semver-2.0.0-9cf)](https://semver.org/spec/v2.0.0.html)

**Warehouse Duct Tape** — small commands that stick your HomeSource tenant to a
spreadsheet. Log in once with Chrome, export inventory, models, or order lines to
CSV/JSON, open in Excel.

> **Not affiliated with [HomeSource Systems](https://homesourcesystems.com).**
> Third-party tools maintained by contributors—not the vendor.

## Who should read what?

| You are… | Start here |
|----------|------------|
| **Warehouse / office staff** — you just want a CSV | **[Getting started](docs/GETTING_STARTED.md)** — plain language, copy-paste commands |
| **New Python developer** — learning the repo | **[For developers](docs/FOR_DEVELOPERS.md)** — architecture, file map, tests |
| **Power user / admin** — every flag and column | **This README** (reference below) |
| **Contributor** — changing code | [CONTRIBUTING.md](CONTRIBUTING.md) |

**Stuck?** Run any command with `-h` or `--help` for examples:

```bash
fetch-physical-inventory -h
```

## What’s included

| Script | Purpose |
|--------|---------|
| [`fetch_physical_inventory.py`](fetch_physical_inventory.py) | All scan lines for one or more physical inventory runs |
| [`fetch_inventory_id.py`](fetch_inventory_id.py) | Serial / inventory records by InventoryId, including timestamp, tags, and pricing fields |
| [`fetch_model.py`](fetch_model.py) | Model catalog records by model number |
| [`fetch_order_detail.py`](fetch_order_detail.py) | Invoiced units per sales order (full API data when available) |
| [`fetch_physical_inventory_with_model.py`](fetch_physical_inventory_with_model.py) | Physical inventory plus manufacturer, category, description, and color |
| [`open_homesource.py`](open_homesource.py) | Shared Selenium login (used internally; not run on its own) |

## Requirements

- **Python 3.10+**
- **Google Chrome** (Selenium 4.6+ manages ChromeDriver automatically)
- A HomeSource account with permission to view the data you export

## Installation

```bash
pip install wdt-tools
```

(After [first publish to PyPI](PUBLISHING.md). Until then, use **from source** below.)

| Command | Purpose |
|---------|---------|
| `fetch-physical-inventory` | Physical inventory runs |
| `fetch-inventory-id` | Inventory serial / serial-grid exports |
| `fetch-model` | Model catalog |
| `fetch-order-detail` | Order / invoiced units |
| `fetch-physical-inventory-with-model` | Inventory + model metadata |

**First export:** see [Getting started](docs/GETTING_STARTED.md) (credentials file + one example).

### From source (developers)

```bash
git clone https://github.com/YOUR_USERNAME/wdt-tools.git
cd wdt-tools
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

pip install -r requirements-dev.txt
# or runtime only: pip install -r requirements.txt
# or editable install: pip install -e .
```

Maintainers: see [PUBLISHING.md](PUBLISHING.md) for releasing new versions to PyPI.

For development (tests and lint), install dev dependencies:

```bash
pip install -r requirements-dev.txt
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full contributor workflow.

## Configuration

Create a credentials file **outside the repo** so secrets are never committed.

**Default path (Windows):**

```
%USERPROFILE%\credentials\wdt-tools\.env
```

**Default path (macOS / Linux):**

```
~/credentials/wdt-tools/.env
```

**Example `.env`:**

```env
APP_USERNAME=your.username
APP_PASSWORD=your.password
HOMESOURCE_BASE_URL=https://your-tenant.homesourcesystems.com
```

| Variable | Required | Description |
|----------|----------|-------------|
| `APP_USERNAME` | Yes | HomeSource login email |
| `APP_PASSWORD` | Yes | HomeSource login password |
| `HOMESOURCE_BASE_URL` | Yes | Tenant base URL (no trailing path), e.g. `https://your-tenant.homesourcesystems.com` |

Use a custom file path with `--credentials-file` on any fetch script.

Override the tenant URL for a single run with `--base-url` (optional).

## Quick start

```bash
fetch-physical-inventory --run-ids 641 -o inventory.csv
fetch-inventory-id --ids 124651 -o serials.csv
fetch-model --models VBW24PNLS -o model.csv
fetch-order-detail --order-ids 17667 -o units.csv
```

Progress → terminal window. Spreadsheet → `-o` file (or stdout if you omit it).

### Help and column preview

```bash
fetch-physical-inventory -h              # colorized usage + examples
fetch-physical-inventory --list-fields   # default columns (numbered table)
fetch-physical-inventory --list-fields --all-fields   # full export guide
```

---

## Reference — `fetch_inventory_id`

Exports serial / inventory rows for one or more `InventoryId` values.

**Default columns:** `_source_query`, `timestamp_utc`, `Order.OrderId`, `Order.DateNeeded`, `Order.OrderDate`, `InventoryId`, `MFGSerialNumber`, `ProductId_FK`, `ModelNumber`, `is_allocated`, `Cost`, `SalespersonCostValue`, `LocationShortName`, `ReceivedDate`, `NonSellable`, `ImgURL`, `MobileImageURL`, `ShortDescription`, `manufacturer.Name`, `location.Name`, `location.Add1`, `location.Zip`, `whse_location.Name`, `purchase_order_item.unit_cost`, `item_tags.value`, and `_error` on failures.

`item_tags.value` is exported as a bracketed list like `[D-DISPLAY, CLEARANCE]` when multiple tags are present.

### Examples

```bash
# Single inventory ID
python fetch_inventory_id.py --ids 124651

# Multiple inventory IDs
python fetch_inventory_id.py --ids 124651,130200 -o serials.csv

# JSON output
python fetch_inventory_id.py --ids 124651 --output-format json -o serials.json

# Include older stock
python fetch_inventory_id.py --ids 124651 --include-aged -o serials.csv

# Include all statuses
python fetch_inventory_id.py --ids 124651 --all-statuses -o serials.csv

# IDs from a CSV file
python fetch_inventory_id.py -i ids.csv -o serials.csv

# Debug login / CAPTCHA issues
python fetch_inventory_id.py --ids 124651 --show-browser

# Show available columns
python fetch_inventory_id.py --list-fields
python fetch_inventory_id.py --list-fields --all-fields
```

**Useful flags:** `--include-aged`, `--all-statuses`, `--only-with-obsolete-onhand`, `--all-fields`, `--page-size`, `--show-browser`

---

## Reference — `fetch_physical_inventory`

Exports every row for one or more physical inventory runs.

**Default columns:** `_source_run_id`, `InventoryId`, `MFGSerialNumber`, `ModelNumber`, scan/location fields, `ScanStatusName`, and related location names. Failed runs produce a row with `_source_run_id` and `_error` only.

### Examples

```bash
# Single run
python fetch_physical_inventory.py --run-ids 641

# Multiple runs → CSV file
python fetch_physical_inventory.py --run-ids 641,642,650 -o inventory.csv

# Run IDs from a CSV (column PhysicalInventoryRunId by default)
python fetch_physical_inventory.py -i runs.csv -o inventory.csv

# JSON output
python fetch_physical_inventory.py --run-ids 641 --output-format json -o inventory.json

# All fields returned by the API
python fetch_physical_inventory.py --run-ids 641 --all-fields -o full.csv

# Debug login (visible browser)
python fetch_physical_inventory.py --run-ids 641 --show-browser
```

**Input options:** `--run-ids`, `-i` / `--input`, `--run-id-column` (default `PhysicalInventoryRunId`), `--input-format csv|json`

---

## Reference — `fetch_model`

Exports model records from the inventory model grid.

**Default:** exact match on `ModelNumber`. Use `--contains` for substring search across Brand, ModelNumber, and ShortDescription.

### Examples

```bash
# Exact model number
python fetch_model.py --models VBW24PNLS

# Several models
python fetch_model.py --models VBW24PNLS,KDFE104HPS -o models.csv

# Fuzzy search
python fetch_model.py --models VBW24 --contains -o matches.csv

# Models from CSV (column ModelNumber by default)
python fetch_model.py -i models.csv -o out.csv

# JSON output
python fetch_model.py --models VBW24PNLS --output-format json -o model.json
```

**Useful flags:** `--only-with-obsolete-onhand`, `--page-size` (default 200), `--all-fields`

---

## Reference — `fetch_order_detail`

Exports one row per invoiced unit for each order.

- **Open orders:** full data from `/sales/orders/search/{OrderId}` (`_source` = `api`).
- **Closed orders:** limited fields scraped from the invoice HTML page (`_source` = `invoice_html`). InventoryId, serial numbers, and cost fields may be blank.

### Examples

```bash
# Single order
python fetch_order_detail.py --order-ids 17667

# Many orders from CSV (column OrderId by default)
python fetch_order_detail.py -i orders.csv -o units.csv

# JSON to stdout
python fetch_order_detail.py --order-ids 17667,20835 --output-format json

# Resume after interruption (skip orders already in output)
python fetch_order_detail.py -i orders.csv -o units.csv --skip-existing units.csv

# Debug login
python fetch_order_detail.py --order-ids 17667 --show-browser
```

---

## Reference — `fetch_physical_inventory_with_model`

Runs the physical inventory export, looks up each distinct `ModelNumber`, and appends:

- `manufacturer.Name`
- `category.Name`
- `ShortDescription`
- `Color`

Uses **one** Chrome login for both steps (faster and gentler on bot detection than running the two scripts separately).

### Examples

```bash
# Default 15-column curated output
python fetch_physical_inventory_with_model.py --run-ids 641 -o joined.csv

# Several runs from CSV
python fetch_physical_inventory_with_model.py -i runs.csv -o joined.csv

# Full inventory fields plus the four model columns
python fetch_physical_inventory_with_model.py --run-ids 641 --all-fields -o full.csv
```

Accepts the same run-ID input options as `fetch_physical_inventory.py`.

---

## Common options

These flags work on all fetch scripts unless noted:

| Flag | Description |
|------|-------------|
| `-o`, `--output` | Write to a file instead of stdout |
| `--output-format csv\|json` | Output format (default: `csv`) |
| `--credentials-file` | Path to `.env` (see [Configuration](#configuration)) |
| `--base-url` | Override `HOMESOURCE_BASE_URL` for one run |
| `--show-browser` | Show Chrome during login (CAPTCHA / debugging) |
| `--delay` | Seconds between requests (default `0.25`) |
| `--timeout` | HTTP timeout in seconds (default `30`) |
| `--quiet` | Less progress on stderr |

## Exit codes

| Code | Meaning |
|------|---------|
| `0` | All items fetched successfully |
| `1` | Some items failed; others succeeded (check `_error` column) |
| `2` | Fatal error (missing credentials, no input, login failure) |

## Troubleshooting

**Login fails or CAPTCHA appears**

```bash
python fetch_physical_inventory.py --run-ids 641 --show-browser
```

Confirm `HOMESOURCE_BASE_URL` matches the URL you use in the browser (scheme + host only, no `/login` suffix).

**`credentials file not found`**

Create the `.env` file at the default path or pass `--credentials-file /path/to/.env`.

**`missing required key(s)`**

Ensure `APP_USERNAME`, `APP_PASSWORD`, and `HOMESOURCE_BASE_URL` are all set and non-empty.

**Closed orders missing inventory fields**

Expected for `fetch_order_detail.py` when `_source` is `invoice_html`. Re-fetch open orders via the API if you need full unit detail.

---

## Versioning

This project follows [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html).

The current version is stored in [`VERSION`](VERSION) (currently **1.0.0**). Release history is in [`CHANGELOG.md`](CHANGELOG.md).

| Part | When to increase | Examples |
|------|------------------|----------|
| **MAJOR** | Incompatible CLI or output contract | Renaming/removing columns, changing required `.env` keys, removing scripts |
| **MINOR** | Backward-compatible features | New script, new optional flag, new optional output columns |
| **PATCH** | Backward-compatible fixes | Bug fixes, clearer errors, documentation |

**Git tags:** tag releases as `vMAJOR.MINOR.PATCH` (e.g. `v1.0.0`):

```bash
git tag -a v1.0.0 -m "Release 1.0.0"
git push origin v1.0.0
```

Pre-release versions may use labels such as `1.1.0-rc.1` per the SemVer spec.

## Development and testing

Contributors should run the automated checks before every commit:

```bash
# After: pip install -r requirements-dev.txt
pytest          # unit tests (no Chrome, no credentials, no network)
ruff check .    # lint
```

GitHub Actions runs the same checks on Python 3.10 and 3.12 for each push and pull request (see [`.github/workflows/ci.yml`](.github/workflows/ci.yml)).

Shared helpers live in [`homesource_common.py`](homesource_common.py). Fetch scripts should import from there instead of duplicating credential parsing, login, or flattening logic.

## Security

- Do **not** commit `.env` files or credentials (see [`.gitignore`](.gitignore)).
- Store credentials only on your machine or in a secrets manager you control.
- These scripts run with your HomeSource user’s permissions; treat output files as sensitive if they contain cost or customer data.

## License

MIT — see [LICENSE](LICENSE).

## Repository layout

```
wdt-tools/
├── docs/
│   ├── GETTING_STARTED.md    # non-developers: setup + daily use
│   └── FOR_DEVELOPERS.md     # architecture + codebase map
├── CHANGELOG.md
├── CONTRIBUTING.md
├── PUBLISHING.md
├── LICENSE
├── README.md
├── VERSION
├── requirements.txt
├── requirements-dev.txt
├── pyproject.toml
├── homesource_common.py      # shared helpers (credentials, login, I/O)
├── open_homesource.py
├── fetch_physical_inventory.py
├── fetch_model.py
├── fetch_order_detail.py
├── fetch_physical_inventory_with_model.py
├── tests/
└── .github/workflows/ci.yml
```
