#!/usr/bin/env python3
"""
fetch_model.py

Fetches model records from the HomeSource model grid via the Kendo
"showAll" endpoint:

    /inventory/model/showAll?{...take/skip/page/pageSize/filter...}

You pass it one or more model numbers; for each one the script issues a
search and collects every matching row.

SEARCH MODE
-----------
By default each input value is matched as an EXACT model number
(Kendo operator "eq" on the ModelNumber field). This avoids pulling in
near-duplicates -- e.g. a stainless-steel and a black variant of the
same product, which a substring match would both return.

Pass --contains to instead use HomeSource's native model-grid search,
which matches the value as a substring (operator "contains") across
three fields: Brand, ModelNumber, and ShortDescription. That is the
fuzzier lookup the website itself performs; use it when you want every
record mentioning the term rather than one exact model.

OBSOLETE FILTER
---------------
HomeSource's model grid applies a default filter requiring
ObsoleteOnHand to be non-null. This script does NOT apply that filter
by default -- you see all models, obsolete or not. Pass
--only-with-obsolete-onhand to re-enable the ObsoleteOnHand neq null
restriction.

OUTPUT COLUMNS
--------------
By default the script writes a curated set of model columns:

    _source_query, ModelNumber, ReplacementCost, ObsoleteDate,
    ShortDescription, LongDescription, Color, DefaultSalePrice,
    OnHand, OnOrder, Allocated, InTransit, Transfer, Sellable,
    NetAvailable, manufacturer.Name, category.Name

(plus _error, which is populated only on failed-query rows).

Pass --all-fields to instead emit every field the endpoint returns.
The full schema is discovered dynamically: each row is flattened, with
nested dicts flattened to dotted keys (e.g. "manufacturer.Name") and
lists JSON-encoded into a single cell. The CSV header is the union of
all keys across all rows.

A row that represents a failed query carries only _source_query and
_error; all other cells are blank.

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
    # One model, exact match, CSV to stdout
    python fetch_model.py --models VBW24PNLS

    # Several models, file out
    python fetch_model.py --models VBW24PNLS,KDFE104HPS -o models.csv

    # Fuzzy substring search across Brand/ModelNumber/ShortDescription
    python fetch_model.py --models VBW24 --contains -o matches.csv

    # Re-apply HomeSource's ObsoleteOnHand neq null filter
    python fetch_model.py --models VBW24PNLS --only-with-obsolete-onhand

    # Models from a CSV file (column "ModelNumber" by default)
    python fetch_model.py -i models.csv -o out.csv

    # Models from a JSON file (flat array or array of objects)
    python fetch_model.py -i models.json -o out.json

    # Piped on stdin
    echo '["VBW24PNLS","KDFE104HPS"]' | python fetch_model.py --input-format json

    # JSON output
    python fetch_model.py --models VBW24PNLS --output-format json

    # Every field the endpoint returns (full dynamic schema)
    python fetch_model.py --models VBW24PNLS --all-fields -o full.csv

    # Watch the browser (debugging login issues / CAPTCHAs)
    python fetch_model.py --models VBW24PNLS --show-browser

OUTPUT FORMATS
--------------
    --output-format csv   (default)  one row per model record
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

import datetime
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
PROVENANCE_COLUMNS = ["_source_query", "_error"]

# Default (curated) output columns. These are dotted paths into the
# flattened record. By default only these are written; pass --all-fields
# to emit the full dynamic union of every key instead.
#
# _source_query is part of provenance and is always present; the
# remaining names are the model fields requested for the default view.
DEFAULT_FIELDS = [
    "_source_query",
    "timestamp_utc",
    "ModelNumber",
    "ProductId_FK",
    "ReplacementCost",
    "ObsoleteDate",
    "ShortDescription",
    "LongDescription",
    "Color",
    "DefaultSalePrice",
    "OnHand",
    "OnOrder",
    "Allocated",
    "InTransit",
    "Transfer",
    "Sellable",
    "NetAvailable",
    "BaseModel",
    "CustomModel",
    "tags",
    "spiffs",
    "manufacturer.Name",
    "manufacturer.Obsolete",
    "type.Name",
    "category.Name",
]

# Rows fetched per request when paging the Kendo envelope.
DEFAULT_PAGE_SIZE = 200

# Fields the website's native model search matches against (used by
# --contains mode).
CONTAINS_FIELDS = ["Brand", "ModelNumber", "ShortDescription"]

ALL_FIELDS_EXTRA_HINTS = (
    "CreatedAt",
    "UpdatedAt",
    "Brand",
    "DefaultSalePrice",
    "ReplacementCost",
    "ObsoleteOnHand",
    "manufacturer.Id",
    "category.Id",
)


def column_catalog() -> hc.ColumnCatalog:
    return hc.ColumnCatalog(
        title="Model catalog export",
        default_fields=DEFAULT_FIELDS,
        all_fields_extra_hints=ALL_FIELDS_EXTRA_HINTS,
    )


flatten_record = hc.flatten_record


def flatten_query(rows: list[Any], query: str) -> list[dict]:
    """Flatten every row of one query and stamp the provenance column."""
    flat: list[dict] = []
    for row in rows:
        rec = flatten_record(row)
        rec["_source_query"] = query
        rec["_error"] = ""
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
    model: str,
    contains: bool,
    only_with_obsolete_onhand: bool,
) -> dict | None:
    """
    Build the Kendo `filter` object for one model search.

    The model condition is always present:
        * exact mode (default):  ModelNumber eq <model>
        * --contains mode:        Brand|ModelNumber|ShortDescription
                                  contains <model>  (OR group)

    The ObsoleteOnHand neq null condition is added only when
    only_with_obsolete_onhand is True. When it is added the two
    conditions are AND-ed together; otherwise the model condition
    stands alone.
    """
    if contains:
        model_cond: dict = {
            "logic": "or",
            "filters": [
                {"field": f, "operator": "contains", "value": model}
                for f in CONTAINS_FIELDS
            ],
        }
    else:
        model_cond = {
            "field": "ModelNumber",
            "operator": "eq",
            "value": model,
        }

    if only_with_obsolete_onhand:
        return {
            "logic": "and",
            "filters": [
                {"field": "ObsoleteOnHand", "operator": "neq", "value": None},
                model_cond,
            ],
        }

    # No obsolete restriction. If the model condition is an OR group it is
    # already a valid top-level filter; if it is a single condition, wrap
    # it in a one-element AND group so the shape is always a filter object.
    if "logic" in model_cond:
        return model_cond
    return {"logic": "and", "filters": [model_cond]}


def _showall_url(
    base_url: str,
    model: str,
    contains: bool,
    only_with_obsolete_onhand: bool,
    take: int,
    skip: int,
    page_size: int,
) -> str:
    """
    Build the model showAll URL. The full Kendo request (paging + filter)
    is passed as a JSON object in the query string, exactly as the site's
    model grid does.
    """
    request_obj = {
        "take": take,
        "skip": skip,
        "page": (skip // page_size) + 1 if page_size else 1,
        "pageSize": page_size,
        "filter": build_filter(model, contains, only_with_obsolete_onhand),
    }
    payload = quote(json.dumps(request_obj, separators=(",", ":")))
    return f"{base_url}/inventory/model/showAll?{payload}"


_extract_rows = hc.extract_kendo_rows


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------
def fetch_model(
    session: requests.Session,
    base_url: str,
    model: str,
    contains: bool,
    only_with_obsolete_onhand: bool,
    referer: str,
    page_size: int,
    timeout: float = 30.0,
) -> list[Any]:
    """
    Fetch every model record matching one search term, paging through
    the Kendo envelope until all rows are collected.
    """
    headers = {"referer": referer}
    collected: list[Any] = []
    skip = 0

    while True:
        url = _showall_url(
            base_url, model, contains, only_with_obsolete_onhand,
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

        # Stop when we have everything, or when the page came back short
        # (last page), or when there is no envelope total to page against.
        if total is None:
            break
        if len(collected) >= total:
            break
        if len(rows) < page_size:
            break
        skip = len(collected)

    return collected


_detect_format = hc.detect_format


def load_models(
    source: str | None,
    fmt: str,
    column: str,
    inline_models: str | None,
) -> list[str]:
    """Return a deduplicated, order-preserving list of model strings."""
    return hc.load_ids_from_input(
        source,
        fmt,
        column,
        inline_models,
        json_key_candidates=(
            column,
            "ModelNumber",
            "Model",
            "model",
            "modelNumber",
            "model_number",
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
        script_label="model",
    )


CLI_HELP_EXAMPLES = """
Examples:
  # One model -> spreadsheet
  fetch-model --models VBW24PNLS -o model.csv

  # Several models
  fetch-model --models VBW24PNLS,KDFE104HPS -o models.csv

  # "Sounds like" search (Brand, model, description)
  fetch-model --models VBW24 --contains -o matches.csv

  # Model list from a CSV file
  fetch-model -i models.csv -o out.csv

  # Troubleshoot login (visible Chrome)
  fetch-model --models VBW24PNLS --show-browser -o model.csv

  # Preview columns
  fetch-model --list-fields
  fetch-model --list-fields --all-fields
"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = hc.create_fetch_parser(
        prog="fetch-model",
        description=(
            "Export model catalog rows for one or more model numbers to CSV "
            "or JSON. Exact match by default; use --contains for a broader "
            "search like the website's model lookup."
        ),
        examples=CLI_HELP_EXAMPLES,
    )
    parser.add_argument(
        "-i", "--input", default=None,
        help="Input file (CSV or JSON) of model numbers. "
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
        "--model-column", default="ModelNumber",
        help="Column/key name to read model numbers from "
             "(default: ModelNumber).",
    )
    parser.add_argument(
        "--models", default=None,
        help="Comma-separated list of model numbers, bypasses --input.",
    )
    parser.add_argument(
        "--contains", action="store_true",
        help="Use HomeSource's native fuzzy search: match each value as a "
             "substring across Brand, ModelNumber and ShortDescription. "
             "Default is an exact ModelNumber match.",
    )
    parser.add_argument(
        "--only-with-obsolete-onhand", action="store_true",
        help="Re-apply HomeSource's default model-grid filter requiring "
             "ObsoleteOnHand to be non-null. By default this filter is "
             "NOT applied, so all models are returned.",
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
    models = load_models(
        args.input, in_fmt, args.model_column, args.models
    )
    if not models:
        sys.stderr.write("ERROR: no model numbers found in input.\n")
        return 2

    # Load credentials and authenticate. The browser closes right after.
    creds = load_credentials(args.credentials_file)
    base_url = (args.base_url or creds["HOMESOURCE_BASE_URL"]).rstrip("/")

    session = build_authenticated_session(
        creds,
        base_url,
        headless=not args.show_browser,
    )

    referer = f"{base_url}/inventory/model"

    # Fetch each model.
    all_rows: list[dict] = []
    failures = 0
    total = len(models)
    mode = "contains" if args.contains else "exact"

    if not args.quiet:
        sys.stderr.write(
            f"Search mode: {mode}. "
            f"Obsolete filter: "
            f"{'ObsoleteOnHand neq null' if args.only_with_obsolete_onhand else 'off'}.\n"
        )

    for idx, model in enumerate(models, 1):
        if not args.quiet:
            sys.stderr.write(f"[{idx}/{total}] Fetching model {model}... ")
            sys.stderr.flush()

        try:
            raw_rows = fetch_model(
                session, base_url, model,
                contains=args.contains,
                only_with_obsolete_onhand=args.only_with_obsolete_onhand,
                referer=referer,
                page_size=args.page_size,
                timeout=args.timeout,
            )
            flat = flatten_query(raw_rows, model)
            if flat:
                all_rows.extend(flat)
                if not args.quiet:
                    sys.stderr.write(f"{len(flat)} row(s)\n")
            else:
                placeholder = {
                    "_source_query": model,
                    "_error": "no matching model records",
                }
                all_rows.append(placeholder)
                if not args.quiet:
                    sys.stderr.write("no rows\n")
        except Exception as e:
            failures += 1
            err_row = {
                "_source_query": model,
                "_error": f"{type(e).__name__}: {e}",
            }
            all_rows.append(err_row)
            if not args.quiet:
                sys.stderr.write(f"FAILED: {e}\n")

        if args.delay and idx < total:
            time.sleep(args.delay)

    # Add timestamp_utc to all rows
    timestamp_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
    for row in all_rows:
        row["timestamp_utc"] = timestamp_utc

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
    """Console entry point when installed via pip (fetch-model)."""
    raise SystemExit(main())


if __name__ == "__main__":
    cli()
