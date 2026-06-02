#!/usr/bin/env python3
"""
fetch_physical_inventory.py

Fetches every row of one or more HomeSource physical inventory runs via
the Kendo grid "showAll" endpoint:

    /inventory/physical/active/showAll?{"PhysicalInventoryRunId":"<id>"}

OUTPUT COLUMNS
--------------
By default the script writes a curated set of inventory columns:

    _source_run_id, InventoryId, MFGSerialNumber, ModelNumber,
    ScannedTime, ScannedDetails.User, ScannedDetails.LocationName,
    ScannedDetails.WHSELocationName, ScanStatusName,
    location.ShortName, whse_location.Name

(plus _error, which is populated only on failed-run rows).

Pass --all-fields to instead emit every field the endpoint returns.
The full schema is discovered dynamically: each row is flattened, with
nested dicts flattened to dotted keys (e.g. "ScannedDetails.User") and
lists JSON-encoded into a single cell. The CSV header is then the union
of all keys across all rows.

A row that represents a failed run carries only _source_run_id and
_error; all other cells are blank.

PAGINATION
----------
The endpoint name ("showAll") implies the full run comes back in one
response, but Kendo grids commonly page server-side. The script handles
both cases automatically:
    * Plain JSON array              -> used as-is.
    * Kendo envelope {data, total}  -> if total > len(data), the script
      pages with take/skip query params until every row is collected.
No configuration is required either way.

AUTHENTICATION
--------------
Login is handled by open_homesource.py (must be in the same directory),
which drives a headless Chrome through the login page. The resulting
cookies are handed to a requests.Session for fast HTTP fetching. Unlike
fetch_order_detail.py, the browser is closed immediately after login --
there is no closed-order HTML fallback for physical inventory runs.

Credentials are read from:
    %USERPROFILE%\\credentials\\wdt-tools\\.env   (default)

Required keys in the .env file:
    APP_USERNAME=yourusername
    APP_PASSWORD=yourpassword
    HOMESOURCE_BASE_URL=https://your-tenant.homesourcesystems.com

USAGE
-----
    # One run, CSV to stdout
    python fetch_physical_inventory.py --run-ids 641

    # Several runs, file out
    python fetch_physical_inventory.py --run-ids 641,642,650 -o runs.csv

    # Run IDs from a CSV file (column "PhysicalInventoryRunId" by default)
    python fetch_physical_inventory.py -i runs.csv -o out.csv

    # Run IDs from a JSON file (flat array or array of objects)
    python fetch_physical_inventory.py -i runs.json -o out.json

    # Piped on stdin
    echo [641,642] | python fetch_physical_inventory.py --input-format json

    # JSON output
    python fetch_physical_inventory.py --run-ids 641 --output-format json

    # Every field the endpoint returns (full dynamic schema)
    python fetch_physical_inventory.py --run-ids 641 --all-fields -o full.csv

    # Watch the browser (debugging login issues / CAPTCHAs)
    python fetch_physical_inventory.py --run-ids 641 --show-browser

OUTPUT FORMATS
--------------
    --output-format csv   (default)  one row per inventory line
    --output-format json             array of objects, same fields

EXIT CODES
----------
    0   all runs fetched successfully
    1   some runs failed (others succeeded; check _error column)
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
PROVENANCE_COLUMNS = ["_source_run_id", "_error"]

# Default (curated) output columns. These are dotted paths into the
# flattened record. By default only these are written; pass --all-fields
# to emit the full dynamic union of every key instead.
#
# _source_run_id is part of provenance and is always present; the
# remaining names are the inventory fields requested for the default view.
DEFAULT_FIELDS = [
    "_source_run_id",
    "InventoryId",
    "MFGSerialNumber",
    "ModelNumber",
    "ScannedTime",
    "ScannedDetails.User",
    "ScannedDetails.LocationName",
    "ScannedDetails.WHSELocationName",
    "ScanStatusName",
    "location.ShortName",
    "whse_location.Name",
]

# When a Kendo envelope is detected and needs paging, fetch this many
# rows per request.
PAGE_SIZE = 500

# Example API keys often seen with --all-fields (varies by tenant).
ALL_FIELDS_EXTRA_HINTS = (
    "CreatedAt",
    "UpdatedAt",
    "PhysicalInventoryItemId",
    "ScanStatusId",
    "PostUser",
    "DeletedAt",
)


def column_catalog() -> hc.ColumnCatalog:
    return hc.ColumnCatalog(
        title="Physical inventory export",
        default_fields=DEFAULT_FIELDS,
        all_fields_extra_hints=ALL_FIELDS_EXTRA_HINTS,
    )


# Re-export for fetch_physical_inventory_with_model and tests.
flatten_record = hc.flatten_record


def flatten_run(rows: list[Any], run_id: str) -> list[dict]:
    """Flatten every row of one run and stamp the provenance column."""
    flat: list[dict] = []
    for row in rows:
        rec = flatten_record(row)
        rec["_source_run_id"] = run_id
        rec["_error"] = ""
        flat.append(rec)
    return flat


def load_credentials(path: str) -> dict[str, str]:
    """Parse .env file; exit 2 on error (CLI convenience)."""
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
    """Login via Selenium; return requests.Session (browser closed)."""
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
# Fetching
# ---------------------------------------------------------------------------
def _showall_url(base_url: str, run_id: str, take: int | None = None,
                 skip: int | None = None) -> str:
    """
    Build the showAll URL. The run filter is passed as a JSON object in
    the query string, exactly as the site's Kendo grid does:

        /inventory/physical/active/showAll?{"PhysicalInventoryRunId":"641"}

    When take/skip are supplied (paging a Kendo envelope) they are added
    as standard query params.
    """
    payload = quote(json.dumps({"PhysicalInventoryRunId": str(run_id)},
                               separators=(",", ":")))
    url = f"{base_url}/inventory/physical/active/showAll?{payload}"
    if take is not None:
        url += f"&take={take}&skip={skip or 0}&pageSize={take}"
    return url


_extract_rows = hc.extract_kendo_rows


def fetch_run(
    session: requests.Session,
    base_url: str,
    run_id: str,
    referer: str,
    timeout: float = 30.0,
) -> list[Any]:
    """
    Fetch every row of one physical inventory run. Pages automatically
    if the endpoint returns a Kendo envelope whose total exceeds the
    rows in the first response.
    """
    headers = {"referer": referer}

    # First request -- no paging params, mirroring the browser's call.
    url = _showall_url(base_url, run_id)
    resp = session.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()

    ctype = resp.headers.get("content-type", "")
    if not resp.text.strip():
        # An empty body is a valid "run has no rows" answer.
        return []
    if "json" not in ctype.lower():
        snippet = resp.text[:200].replace("\n", " ")
        raise RuntimeError(
            f"Non-JSON response (content-type={ctype!r}); "
            f"session may have expired. Body: {snippet}"
        )

    rows, total = _extract_rows(resp.json())

    # If it was a Kendo envelope and there is more data than we received,
    # page through the remainder.
    if total is not None and total > len(rows) and len(rows) > 0:
        collected = list(rows)
        while len(collected) < total:
            page_url = _showall_url(
                base_url, run_id, take=PAGE_SIZE, skip=len(collected)
            )
            page_resp = session.get(page_url, headers=headers, timeout=timeout)
            page_resp.raise_for_status()
            if not page_resp.text.strip():
                break
            page_rows, _ = _extract_rows(page_resp.json())
            if not page_rows:
                break
            collected.extend(page_rows)
        rows = collected

    return rows


_detect_format = hc.detect_format


def load_run_ids(
    source: str | None,
    fmt: str,
    column: str,
    inline_ids: str | None,
) -> list[str]:
    """Return a deduplicated, order-preserving list of run ID strings."""
    return hc.load_ids_from_input(
        source,
        fmt,
        column,
        inline_ids,
        json_key_candidates=(
            column,
            "PhysicalInventoryRunId",
            "RunId",
            "run_id",
            "runId",
            "Id",
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
  # One run -> spreadsheet file (easiest)
  fetch-physical-inventory --run-ids 641 -o inventory.csv

  # Several runs
  fetch-physical-inventory --run-ids 641,642,650 -o inventory.csv

  # Run IDs from a CSV (column PhysicalInventoryRunId by default)
  fetch-physical-inventory -i runs.csv -o inventory.csv

  # See Chrome while logging in (CAPTCHA / troubleshooting)
  fetch-physical-inventory --run-ids 641 --show-browser -o inventory.csv

  # Every field the API returns (advanced)
  fetch-physical-inventory --run-ids 641 --all-fields -o full.csv

  # Preview column names (colorized tables)
  fetch-physical-inventory --list-fields
  fetch-physical-inventory --list-fields --all-fields
"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = hc.create_fetch_parser(
        prog="fetch-physical-inventory",
        description=(
            "Export physical inventory scan lines for one or more run IDs to "
            "CSV or JSON. Logs into your HomeSource tenant once, then downloads "
            "all rows for each run. Use -o to save a file for Excel."
        ),
        examples=CLI_HELP_EXAMPLES,
    )
    parser.add_argument(
        "-i", "--input", default=None,
        help="Input file (CSV or JSON) of run IDs. Omit or use '-' for stdin.",
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
        "--run-id-column", default="PhysicalInventoryRunId",
        help="Column/key name to read run IDs from "
             "(default: PhysicalInventoryRunId).",
    )
    parser.add_argument(
        "--run-ids", default=None,
        help="Comma-separated list of physical inventory run IDs, "
             "bypasses --input.",
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
        "--all-fields", action="store_true",
        help="Emit every field returned by the endpoint (dynamic union of "
             "all keys). See them with --list-fields --all-fields.",
    )
    parser.add_argument(
        "--delay", type=float, default=0.25,
        help="Seconds to wait between runs (default: 0.25).",
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

    in_fmt  = _detect_format(args.input,  args.input_format)
    out_fmt = _detect_format(args.output, args.output_format)

    # Validate input before launching Chrome.
    run_ids = load_run_ids(
        args.input, in_fmt, args.run_id_column, args.run_ids
    )
    if not run_ids:
        sys.stderr.write("ERROR: no run IDs found in input.\n")
        return 2

    # Load credentials and authenticate. The browser closes right after.
    creds = load_credentials(args.credentials_file)
    base_url = (args.base_url or creds["HOMESOURCE_BASE_URL"]).rstrip("/")

    session = build_authenticated_session(
        creds,
        base_url,
        headless=not args.show_browser,
    )

    # Fetch each run.
    all_rows: list[dict] = []
    failures = 0
    total = len(run_ids)

    for idx, rid in enumerate(run_ids, 1):
        if not args.quiet:
            sys.stderr.write(f"[{idx}/{total}] Fetching run {rid}... ")
            sys.stderr.flush()

        referer = f"{base_url}/inventory/physical/active?PhysicalInventoryRunId={rid}"
        try:
            raw_rows = fetch_run(
                session, base_url, rid, referer, timeout=args.timeout
            )
            flat = flatten_run(raw_rows, rid)
            if flat:
                all_rows.extend(flat)
                if not args.quiet:
                    sys.stderr.write(f"{len(flat)} row(s)\n")
            else:
                placeholder = {
                    "_source_run_id": rid,
                    "_error": "run found but has no inventory rows",
                }
                all_rows.append(placeholder)
                if not args.quiet:
                    sys.stderr.write("no rows\n")
        except Exception as e:
            failures += 1
            err_row = {
                "_source_run_id": rid,
                "_error": f"{type(e).__name__}: {e}",
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
            f"{total - failures}/{total} run(s) succeeded"
            + (f", {failures} failed" if failures else "")
            + ".\n"
        )

    if failures == total:
        return 2
    return 1 if failures else 0


def cli() -> None:
    """Console entry point when installed via pip (fetch-physical-inventory)."""
    raise SystemExit(main())


if __name__ == "__main__":
    cli()
