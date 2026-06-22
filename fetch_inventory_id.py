#!/usr/bin/env python3
"""
fetch_inventory_id.py

Fetches serial/inventory records from the HomeSource serial grid via
the Kendo "showAll" endpoint:

    /inventory/serial/showAll?{...take/skip/page/pageSize/filter...}

You pass it one or more inventory IDs; for each one the script issues a
search and collects every matching row.

FILTERS
-------
By default, three conditions are AND-ed together (mirroring the
website's serial grid):

    InventoryId  eq  <value>
    Age          eq  0          (new stock)
    InventoryStatus eq "1"     (active/available)

Pass --include-aged to drop the Age=0 restriction and return stock of
any age. Pass --all-statuses to drop the InventoryStatus="1"
restriction and return every status.

OBSOLETE FILTER
---------------
Pass --only-with-obsolete-onhand to add an ObsoleteOnHand neq null
restriction, as some HomeSource grids apply by default.

OUTPUT COLUMNS
--------------
By default the script writes a curated set of columns:

    _source_query, Order.OrderId, Order.DateNeeded, Order.OrderDate,
    InventoryId, MFGSerialNumber, Cost, ReceivedDate, NonSellable,
    ImgURL, MobileImageURL, ShortDescription, manufacturer.Name,
    location.Name, location.Add1, location.Zip, whse_location.Name

(plus _error, which is populated only on failed-query rows).

Pass --all-fields to instead emit every field the endpoint returns.
The full schema is discovered dynamically: each row is flattened, with
nested dicts flattened to dotted keys (e.g. "manufacturer.Name") and
lists JSON-encoded into a single cell. The CSV header is the union of
all keys across all rows.

PAGINATION
----------
This endpoint is explicitly paged (take/skip/page/pageSize). The script
pages automatically: it reads `total` from the Kendo envelope and walks
`skip` until every row is collected. Page size defaults to 200 rows per
request (override with --page-size).

AUTHENTICATION
--------------
Login is handled by open_homesource.py (must be in the same directory),
which drives a headless Chrome through the login page. The resulting
cookies are handed to a requests.Session for fast HTTP fetching. The
browser is closed immediately after login.

Credentials are read from:
    %USERPROFILE%\\credentials\\wdt-tools\\.env   (default)

Required keys in the .env file:
    APP_USERNAME=yourusername
    APP_PASSWORD=yourpassword
    HOMESOURCE_BASE_URL=https://your-tenant.homesourcesystems.com

USAGE
-----
    # One inventory ID, CSV to stdout
    python fetch_inventory_id.py --ids 124651

    # Several IDs, file out
    python fetch_inventory_id.py --ids 124651,130200 -o serials.csv

    # Include aged stock (drop Age=0 filter)
    python fetch_inventory_id.py --ids 124651 --include-aged

    # Include all statuses (drop InventoryStatus="1" filter)
    python fetch_inventory_id.py --ids 124651 --all-statuses

    # IDs from a CSV file (column "InventoryId" by default)
    python fetch_inventory_id.py -i ids.csv -o out.csv

    # IDs from a JSON file (flat array or array of objects)
    python fetch_inventory_id.py -i ids.json -o out.json

    # Piped on stdin
    echo '["124651","130200"]' | python fetch_inventory_id.py --input-format json

    # JSON output
    python fetch_inventory_id.py --ids 124651 --output-format json

    # Every field the endpoint returns (full dynamic schema)
    python fetch_inventory_id.py --ids 124651 --all-fields -o full.csv

    # Watch the browser (debugging login issues / CAPTCHAs)
    python fetch_inventory_id.py --ids 124651 --show-browser

OUTPUT FORMATS
--------------
    --output-format csv   (default)  one row per serial record
    --output-format json             array of objects, same fields

EXIT CODES
----------
    0   all queries fetched successfully
    1   some queries failed (others succeeded; check _error column)
    2   fatal error (bad credentials, no input, auth failure)

REQUIREMENTS
------------
    pip install -r requirements.txt
    open_homesource.py and homesource_common.py must be in the same directory.
    Chrome must be installed (Selenium 4.6+ manages chromedriver automatically).
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import homesource_common as hc

try:
    import requests
except ImportError:
    sys.stderr.write("ERROR: requests not installed. Run: pip install -r requirements.txt\n")
    sys.exit(2)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_CREDENTIALS_FILE = hc.DEFAULT_CREDENTIALS_FILE

# Provenance columns always emitted first, in this order.
PROVENANCE_COLUMNS = ["_source_query", "_error"]

# Default (curated) output columns. These are dotted paths into the
# flattened record. By default only these are written; pass --all-fields
# to emit the full dynamic union of every key instead.
DEFAULT_FIELDS = [
    "_source_query",
    "timestamp_utc",
    "Order.OrderId",
    "Order.DateNeeded",
    "Order.OrderDate",
    "InventoryId",
    "MFGSerialNumber",
    "ProductId_FK",
    "ModelNumber",
    "is_allocated",
    "Cost",
    "SalespersonCostValue",
    "LocationShortName",
    "ReceivedDate",
    "NonSellable",
    "ImgURL",
    "MobileImageURL",
    "ShortDescription",
    "manufacturer.Name",
    "location.Name",
    "location.Add1",
    "location.Zip",
    "whse_location.Name",
    "purchase_order_item.unit_cost",
    "item_tags.value",
]

# Rows fetched per request when paging the Kendo envelope.
DEFAULT_PAGE_SIZE = 200

ALL_FIELDS_EXTRA_HINTS = (
    "InventoryId",
    "MFGSerialNumber",
    "Cost",
    "ReceivedDate",
    "Age",
    "InventoryStatus",
    "NonSellable",
    "ImgURL",
    "MobileImageURL",
    "ShortDescription",
    "Order.OrderId",
    "Order.DateNeeded",
    "Order.OrderDate",
    "manufacturer.Id",
    "manufacturer.Name",
    "location.Id",
    "location.Name",
    "location.Add1",
    "location.Add2",
    "location.City",
    "location.State",
    "location.Zip",
    "whse_location.Id",
    "whse_location.Name",
    "category.Id",
    "category.Name",
    "CreatedAt",
    "UpdatedAt",
)


def column_catalog() -> hc.ColumnCatalog:
    return hc.ColumnCatalog(
        title="Inventory serial export",
        default_fields=DEFAULT_FIELDS,
        all_fields_extra_hints=ALL_FIELDS_EXTRA_HINTS,
    )


flatten_record = hc.flatten_record


def _format_item_tags_value(tags: Any) -> str:
    if not isinstance(tags, list):
        return ""

    values: list[str] = []
    for tag in tags:
        if isinstance(tag, dict):
            value = tag.get("Value")
            if value is None:
                value = tag.get("value")
        else:
            value = tag
        if value is None:
            continue
        text = str(value).strip()
        if text:
            values.append(text)

    return f"[{', '.join(values)}]" if values else ""


def _get_inventory_tags(row: dict[str, Any]) -> Any:
    tags = row.get("tags")
    if tags is None:
        tags = row.get("item_tags")
    return tags


def _timestamp_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def flatten_query(rows: list[Any], query: str, timestamp_utc: str) -> list[dict]:
    """Flatten every row of one query and stamp the provenance column."""
    flat: list[dict] = []
    for row in rows:
        rec = flatten_record(row)
        if isinstance(row, dict):
            rec["item_tags.value"] = _format_item_tags_value(_get_inventory_tags(row))
        rec["_source_query"] = query
        rec["_error"] = ""
        rec["timestamp_utc"] = timestamp_utc
        flat.append(rec)
    return flat


def load_credentials(path: str) -> dict[str, str]:
    try:
        return hc.load_credentials(path)
    except hc.CredentialsError as e:
        sys.stderr.write(f"ERROR: {e}\n")
        sys.exit(2)


def build_authenticated_session(
    creds: dict[str, str],
    base_url: str,
    headless: bool,
    login_timeout: float = 30.0,
) -> requests.Session:
    try:
        return hc.build_authenticated_session(
            creds,
            base_url,
            headless,
            keep_driver=False,
            login_timeout=login_timeout,
            extra_session_headers={"content-type": "application/json"},
        )
    except ImportError as e:
        sys.stderr.write(f"ERROR: {e}\n")
        sys.exit(2)
    except hc.LoginError as e:
        sys.stderr.write(f"ERROR: {e}\n")
        sys.exit(2)


# ---------------------------------------------------------------------------
# Kendo filter construction
# ---------------------------------------------------------------------------
def build_filter(
    inventory_id: str,
    include_aged: bool,
    all_statuses: bool,
    only_with_obsolete_onhand: bool,
) -> dict:
    """
    Build the Kendo `filter` object for one inventory ID search.

    Always includes:
        InventoryId eq <inventory_id>   (wrapped in OR group)

    Conditionally includes (both on by default):
        Age eq 0                        (dropped by --include-aged)
        InventoryStatus eq "1"          (dropped by --all-statuses)

    Optionally includes:
        ObsoleteOnHand neq null         (added by --only-with-obsolete-onhand)

    All conditions are AND-ed together.
    """
    filters: list[dict] = []

    # InventoryId condition (wrapped in OR group like the website does)
    filters.append({
        "logic": "or",
        "filters": [
            {"field": "InventoryId", "operator": "eq", "value": inventory_id},
        ],
    })

    # Age filter (default: new stock only)
    if not include_aged:
        filters.append(
            {"field": "Age", "operator": "eq", "value": 0},
        )

    # InventoryStatus filter (default: active only)
    if not all_statuses:
        filters.append({
            "logic": "or",
            "filters": [
                {"field": "InventoryStatus", "operator": "eq", "value": "1"},
            ],
        })

    # Optional obsolete restriction
    if only_with_obsolete_onhand:
        filters.append(
            {"field": "ObsoleteOnHand", "operator": "neq", "value": None},
        )

    return {"logic": "and", "filters": filters}


def _showall_url(
    base_url: str,
    inventory_id: str,
    include_aged: bool,
    all_statuses: bool,
    only_with_obsolete_onhand: bool,
    take: int,
    skip: int,
    page_size: int,
) -> str:
    """
    Build the serial showAll URL. The full Kendo request (paging +
    filter) is passed as a JSON object in the query string, exactly as
    the site's serial grid does.
    """
    request_obj = {
        "take": take,
        "skip": skip,
        "page": (skip // page_size) + 1 if page_size else 1,
        "pageSize": page_size,
        "filter": build_filter(
            inventory_id, include_aged, all_statuses, only_with_obsolete_onhand,
        ),
    }
    payload = quote(json.dumps(request_obj, separators=(",", ":")))
    return f"{base_url}/inventory/serial/showAll?{payload}"


_extract_rows = hc.extract_kendo_rows


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------
def fetch_inventory_id(
    session: requests.Session,
    base_url: str,
    inventory_id: str,
    include_aged: bool,
    all_statuses: bool,
    only_with_obsolete_onhand: bool,
    referer: str,
    page_size: int,
    timeout: float = 30.0,
) -> list[Any]:
    """
    Fetch every serial record matching one inventory ID, paging through
    the Kendo envelope until all rows are collected.
    """
    headers = {"referer": referer}
    collected: list[Any] = []
    skip = 0

    while True:
        url = _showall_url(
            base_url, inventory_id, include_aged, all_statuses,
            only_with_obsolete_onhand,
            take=page_size, skip=skip, page_size=page_size,
        )
        resp = session.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()

        ctype = resp.headers.get("content-type", "")
        if not resp.text.strip():
            break
        if "json" not in ctype.lower():
            snippet = resp.text[:200].replace("\n", " ")
            raise RuntimeError(
                f"Non-JSON response (content-type={ctype!r}); "
                f"session may have expired. Body: {snippet}"
            )

        rows, total = _extract_rows(resp.json())
        if not rows:
            break
        collected.extend(rows)

        if total is None:
            break
        if len(collected) >= total:
            break
        if len(rows) < page_size:
            break
        skip = len(collected)

    return collected


_detect_format = hc.detect_format


def load_inventory_ids(
    source: str | None,
    fmt: str,
    column: str,
    inline_ids: str | None,
) -> list[str]:
    """Return a deduplicated, order-preserving list of inventory ID strings."""
    return hc.load_ids_from_input(
        source,
        fmt,
        column,
        inline_ids,
        json_key_candidates=(
            column,
            "InventoryId",
            "inventory_id",
            "inventoryId",
            "Id",
            "id",
        ),
    )


def emit_rows(
    rows: list[dict],
    out_path: str | None,
    fmt: str,
    all_fields: bool = False,
    quiet: bool = False,
) -> int:
    """Write rows to a file or stdout. Returns the count written."""
    return hc.emit_curated_rows(
        rows,
        out_path,
        fmt,
        provenance_columns=PROVENANCE_COLUMNS,
        default_fields=DEFAULT_FIELDS,
        all_fields=all_fields,
        quiet=quiet,
        script_label="inventory",
    )


CLI_HELP_EXAMPLES = """
Examples:
  # One inventory ID -> spreadsheet
  fetch-inventory-id --ids 124651 -o serial.csv

  # Several IDs
  fetch-inventory-id --ids 124651,130200 -o serials.csv

  # Include aged stock (drop the Age=0 filter)
  fetch-inventory-id --ids 124651 --include-aged -o serials.csv

  # Include all statuses (drop the InventoryStatus="1" filter)
  fetch-inventory-id --ids 124651 --all-statuses -o serials.csv

  # ID list from a CSV file
  fetch-inventory-id -i ids.csv -o out.csv

  # Troubleshoot login (visible Chrome)
  fetch-inventory-id --ids 124651 --show-browser -o serial.csv

  # Preview columns
  fetch-inventory-id --list-fields
  fetch-inventory-id --list-fields --all-fields
"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = hc.create_fetch_parser(
        prog="fetch-inventory-id",
        description=(
            "Export serial/inventory rows for one or more inventory IDs to "
            "CSV or JSON. Filters to new (Age=0), active "
            "(InventoryStatus=1) stock by default."
        ),
        examples=CLI_HELP_EXAMPLES,
    )
    parser.add_argument(
        "-i", "--input", default=None,
        help="Input file (CSV or JSON) of inventory IDs. "
             "Omit or use '-' for stdin.",
    )
    parser.add_argument(
        "-o", "--output", default=None,
        help="Output file. Omit or use '-' for stdout.",
    )
    parser.add_argument(
        "--input-format", choices=["csv", "json"], default=None,
        help="Force input format (auto-detected from file extension otherwise).",
    )
    parser.add_argument(
        "--output-format", choices=["csv", "json"], default=None,
        help="Force output format (auto-detected from extension; default csv).",
    )
    parser.add_argument(
        "--id-column", default="InventoryId",
        help="Column/key name to read inventory IDs from "
             "(default: InventoryId).",
    )
    parser.add_argument(
        "--ids", default=None,
        help="Comma-separated list of inventory IDs, bypasses --input.",
    )
    parser.add_argument(
        "--include-aged", action="store_true",
        help="Drop the Age=0 filter and return stock of any age.",
    )
    parser.add_argument(
        "--all-statuses", action="store_true",
        help="Drop the InventoryStatus='1' filter and return all statuses.",
    )
    parser.add_argument(
        "--only-with-obsolete-onhand", action="store_true",
        help="Add an ObsoleteOnHand neq null restriction.",
    )
    parser.add_argument(
        "--all-fields", action="store_true",
        help="Emit every field returned by the endpoint (dynamic union). "
             "See them with --list-fields --all-fields.",
    )
    parser.add_argument(
        "--page-size", type=int, default=DEFAULT_PAGE_SIZE,
        help=f"Rows fetched per request when paging "
             f"(default: {DEFAULT_PAGE_SIZE}).",
    )
    parser.add_argument(
        "--credentials-file", default=DEFAULT_CREDENTIALS_FILE,
        help=f"Path to .env file with APP_USERNAME, APP_PASSWORD, and "
             f"HOMESOURCE_BASE_URL (default: {DEFAULT_CREDENTIALS_FILE}).",
    )
    parser.add_argument(
        "--base-url", default=None,
        help="Override HOMESOURCE_BASE_URL from the credentials file.",
    )
    parser.add_argument(
        "--show-browser", action="store_true",
        help="Show the Chrome window instead of running headless. "
             "Useful for debugging login issues or CAPTCHAs.",
    )
    parser.add_argument(
        "--delay", type=float, default=0.25,
        help="Seconds to wait between queries (default: 0.25).",
    )
    parser.add_argument(
        "--timeout", type=float, default=30.0,
        help="Per-request timeout in seconds (default: 30).",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="Suppress progress output on stderr.",
    )
    hc.add_list_fields_argument(parser)
    hc.add_version_argument(parser)
    args = parser.parse_args(argv)

    if args.list_fields:
        return hc.print_column_catalog(column_catalog(), all_fields=args.all_fields)

    if args.page_size < 1:
        sys.stderr.write("ERROR: --page-size must be at least 1.\n")
        return 2

    in_fmt  = _detect_format(args.input,  args.input_format)
    out_fmt = _detect_format(args.output, args.output_format)

    # Validate input before launching Chrome.
    inv_ids = load_inventory_ids(
        args.input, in_fmt, args.id_column, args.ids
    )
    if not inv_ids:
        sys.stderr.write("ERROR: no inventory IDs found in input.\n")
        return 2

    # Load credentials and authenticate. The browser closes right after.
    creds = load_credentials(args.credentials_file)
    base_url = (args.base_url or creds["HOMESOURCE_BASE_URL"]).rstrip("/")

    session = build_authenticated_session(
        creds,
        base_url,
        headless=not args.show_browser,
    )

    referer = f"{base_url}/inventory/serial"

    # Fetch each inventory ID.
    all_rows: list[dict] = []
    failures = 0
    total = len(inv_ids)

    if not args.quiet:
        filters_active = []
        if not args.include_aged:
            filters_active.append("Age=0")
        if not args.all_statuses:
            filters_active.append("InventoryStatus=1")
        if args.only_with_obsolete_onhand:
            filters_active.append("ObsoleteOnHand neq null")
        filter_desc = ", ".join(filters_active) if filters_active else "none"
        sys.stderr.write(f"Active filters: {filter_desc}.\n")

    for idx, inv_id in enumerate(inv_ids, 1):
        if not args.quiet:
            sys.stderr.write(f"[{idx}/{total}] Fetching InventoryId {inv_id}... ")
            sys.stderr.flush()

        timestamp_utc = _timestamp_utc()
        try:
            raw_rows = fetch_inventory_id(
                session, base_url, inv_id,
                include_aged=args.include_aged,
                all_statuses=args.all_statuses,
                only_with_obsolete_onhand=args.only_with_obsolete_onhand,
                referer=referer,
                page_size=args.page_size,
                timeout=args.timeout,
            )
            flat = flatten_query(raw_rows, inv_id, timestamp_utc)
            if flat:
                all_rows.extend(flat)
                if not args.quiet:
                    sys.stderr.write(f"{len(flat)} row(s)\n")
            else:
                placeholder = {
                    "_source_query": inv_id,
                    "_error": "no matching serial records",
                    "timestamp_utc": timestamp_utc,
                }
                all_rows.append(placeholder)
                if not args.quiet:
                    sys.stderr.write("no rows\n")
        except Exception as e:
            failures += 1
            err_row = {
                "_source_query": inv_id,
                "_error": f"{type(e).__name__}: {e}",
                "timestamp_utc": timestamp_utc,
            }
            all_rows.append(err_row)
            if not args.quiet:
                sys.stderr.write(f"FAILED: {e}\n")

        if args.delay and idx < total:
            time.sleep(args.delay)

    count = emit_rows(
        all_rows, args.output, out_fmt,
        all_fields=args.all_fields,
        quiet=args.quiet,
    )
    if not args.quiet:
        sys.stderr.write(
            f"\nDone. {count} row(s) written. "
            f"{total - failures}/{total} query(ies) succeeded"
            + (f", {failures} failed" if failures else "")
            + ".\n"
        )

    if failures == total:
        return 2
    return 1 if failures else 0


def cli() -> None:
    """Console entry point when installed via pip (fetch-inventory-id)."""
    raise SystemExit(main())


if __name__ == "__main__":
    cli()