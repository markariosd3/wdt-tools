#!/usr/bin/env python3
"""
fetch_physical_inventory_with_model.py

Pipeline that joins physical-inventory rows to model-level catalog
metadata. For one or more PhysicalInventoryRunId values, it:

    1. Fetches every row of each run (fetch_physical_inventory).
    2. Collects the unique non-blank ModelNumber values seen.
    3. Looks each model up with an exact-match search (fetch_model).
    4. Joins manufacturer.Name, category.Name, ShortDescription and
       Color onto every inventory row.

The output is the inventory script's curated 11 columns plus those four
appended fields, so 15 columns total (plus _error, populated only on
failed runs). Pass --all-fields to instead emit the inventory script's
full dynamic union with the four model columns appended.

ONE AUTH SESSION
----------------
The pipeline imports the two fetcher modules and reuses ONE authenticated
session for both phases. There is a single Chrome launch and a single
login, which is meaningfully faster than running the two scripts back to
back and avoids tripping DataDome with rapid successive logins.

JOIN BEHAVIOR
-------------
EVERY inventory row is kept, regardless of what the model lookup returns:

    * Row has no ModelNumber  -> four new columns are blank.
    * ModelNumber not found    -> four new columns are blank.
    * ModelNumber returns one  -> four columns populated from that record.
    * ModelNumber returns many -> four columns set to "<multiple>" so the
                                  ambiguity is visible in the output.
                                  (Exact-match search should not normally
                                  return more than one record, but
                                  HomeSource does not enforce uniqueness
                                  on ModelNumber.)

Failed-run placeholder rows (rows that exist only because a run errored
out) pass through with their four new columns blank.

USAGE
-----
    # One run, default curated output
    python fetch_physical_inventory_with_model.py --run-ids 641 -o joined.csv

    # Several runs
    python fetch_physical_inventory_with_model.py --run-ids 641,642,650 -o joined.csv

    # Run IDs from a CSV file (column "PhysicalInventoryRunId" by default)
    python fetch_physical_inventory_with_model.py -i runs.csv -o joined.csv

    # Inventory side with every field, model fields still appended
    python fetch_physical_inventory_with_model.py --run-ids 641 --all-fields -o full.csv

    # JSON output
    python fetch_physical_inventory_with_model.py --run-ids 641 --output-format json

    # Watch the browser (debugging login issues / CAPTCHAs)
    python fetch_physical_inventory_with_model.py --run-ids 641 --show-browser

EXIT CODES
----------
    0   all runs and all model lookups succeeded
    1   some runs or model lookups failed (others succeeded)
    2   fatal error (bad credentials, no input, auth failure)

REQUIREMENTS
------------
    pip install -r requirements.txt
    fetch_physical_inventory.py, fetch_model.py, homesource_common.py, and
    open_homesource.py must be in the same directory as this script.
"""

from __future__ import annotations

import sys
import time

import homesource_common as hc

# Reuse everything from the two fetchers; we own the same directory.
try:
    import fetch_model as fm
    import fetch_physical_inventory as fpi
except ImportError as e:
    sys.stderr.write(
        f"ERROR: could not import fetcher modules: {e}\n"
        f"fetch_physical_inventory.py and fetch_model.py must be in the "
        f"same directory as this script.\n"
    )
    sys.exit(2)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
# The four model fields we append to each inventory row.
MODEL_APPEND_FIELDS = [
    "manufacturer.Name",
    "category.Name",
    "ShortDescription",
    "Color",
]

# Sentinel used when an exact-match search returns more than one model
# record. Picked to be visually obvious in CSV output and unlikely to
# collide with any real value.
MULTIPLE_MATCH_SENTINEL = "<multiple>"


def column_catalog() -> hc.ColumnCatalog:
    default_cols = list(fpi.DEFAULT_FIELDS)
    for col in MODEL_APPEND_FIELDS:
        if col not in default_cols:
            default_cols.append(col)
    return hc.ColumnCatalog(
        title="Physical inventory + model metadata",
        default_fields=default_cols,
        appended_fields=MODEL_APPEND_FIELDS,
        all_fields_extra_hints=fpi.ALL_FIELDS_EXTRA_HINTS,
    )


# ---------------------------------------------------------------------------
# Model lookup
# ---------------------------------------------------------------------------
def build_model_lookup(
    session,
    base_url: str,
    models: list[str],
    referer: str,
    page_size: int,
    timeout: float,
    delay: float,
    quiet: bool,
) -> tuple[dict[str, dict], dict[str, str], int]:
    """
    Look each model up via exact-match search. Returns three things:

        lookup    -- {ModelNumber -> dict of the four append fields}
                     Multi-match models map to a dict whose values are
                     all MULTIPLE_MATCH_SENTINEL.
        errors    -- {ModelNumber -> error message}  for queries that
                     failed outright. The model is still present as a
                     key in `lookup` with blank values so the join is
                     simple.
        failures  -- count of failed queries (== len(errors)).
    """
    lookup: dict[str, dict] = {}
    errors: dict[str, str] = {}
    failures = 0
    total = len(models)

    for idx, model in enumerate(models, 1):
        if not quiet:
            sys.stderr.write(f"  [{idx}/{total}] Looking up {model}... ")
            sys.stderr.flush()

        try:
            raw_rows = fm.fetch_model(
                session, base_url, model,
                contains=False,                  # exact match
                only_with_obsolete_onhand=False, # see all models
                referer=referer,
                page_size=page_size,
                timeout=timeout,
            )
        except Exception as e:
            failures += 1
            errors[model] = f"{type(e).__name__}: {e}"
            lookup[model] = {f: "" for f in MODEL_APPEND_FIELDS}
            if not quiet:
                sys.stderr.write(f"FAILED: {e}\n")
            if delay and idx < total:
                time.sleep(delay)
            continue

        # Flatten so we can read dotted-key fields like manufacturer.Name.
        flat = [fm.flatten_record(r) for r in raw_rows]

        if not flat:
            lookup[model] = {f: "" for f in MODEL_APPEND_FIELDS}
            if not quiet:
                sys.stderr.write("no match\n")
        elif len(flat) == 1:
            rec = flat[0]
            lookup[model] = {f: rec.get(f, "") for f in MODEL_APPEND_FIELDS}
            if not quiet:
                sys.stderr.write("1 match\n")
        else:
            # More than one model returned for an exact-match search.
            # Don't silently pick one -- mark every appended cell with
            # the sentinel so the ambiguity is visible in the output.
            lookup[model] = {f: MULTIPLE_MATCH_SENTINEL
                             for f in MODEL_APPEND_FIELDS}
            if not quiet:
                sys.stderr.write(
                    f"{len(flat)} matches (sentinel applied)\n"
                )

        if delay and idx < total:
            time.sleep(delay)

    return lookup, errors, failures


# ---------------------------------------------------------------------------
# Join
# ---------------------------------------------------------------------------
def append_model_fields(
    inventory_rows: list[dict],
    lookup: dict[str, dict],
) -> None:
    """
    Mutate inventory_rows in place: for each row, add the four model
    columns. Rows with no ModelNumber and rows whose ModelNumber is
    not in `lookup` get blank values.
    """
    blank = {f: "" for f in MODEL_APPEND_FIELDS}
    for row in inventory_rows:
        model = row.get("ModelNumber")
        if model is None or model == "":
            row.update(blank)
            continue
        # ModelNumber may have been stored as int/float by the source;
        # the lookup is keyed by string, so normalize.
        key = str(model)
        row.update(lookup.get(key, blank))


# ---------------------------------------------------------------------------
# Output (mirrors fetch_physical_inventory's emit_rows but with the
# four model columns appended to whichever column set is in use)
# ---------------------------------------------------------------------------
def emit_joined(
    rows: list[dict],
    out_path: str | None,
    fmt: str,
    all_fields: bool,
    quiet: bool,
) -> int:
    """
    Build the column list using the same rules fetch_physical_inventory
    uses, then append the four model columns. Write CSV or JSON.
    """
    if all_fields:
        columns = hc.build_all_columns(rows, fpi.PROVENANCE_COLUMNS)
    else:
        columns = hc.build_curated_columns(
            rows,
            fpi.PROVENANCE_COLUMNS,
            fpi.DEFAULT_FIELDS,
            quiet=quiet,
            script_label="inventory",
        )

    for c in MODEL_APPEND_FIELDS:
        if c not in columns:
            columns.append(c)

    return hc.emit_tabular_rows(rows, out_path, fmt, columns)


CLI_HELP_EXAMPLES = """
Examples:
  # Best default: inventory + manufacturer, category, description, color
  fetch-physical-inventory-with-model --run-ids 641 -o joined.csv

  # Several runs from a CSV list
  fetch-physical-inventory-with-model -i runs.csv -o joined.csv

  # Troubleshoot login (visible Chrome)
  fetch-physical-inventory-with-model --run-ids 641 --show-browser -o joined.csv

notes:
  One login for both steps (faster than running inventory + model separately).
  Adds: manufacturer.Name, category.Name, ShortDescription, Color.
"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = hc.create_fetch_parser(
        prog="fetch-physical-inventory-with-model",
        description=(
            "Export a physical inventory run and add model catalog columns "
            "(manufacturer, category, description, color) on each row. "
            "One login, one spreadsheet—good everyday 'duct tape' command."
        ),
        examples=CLI_HELP_EXAMPLES,
    )
    # Inventory-side input args (same shape as fetch_physical_inventory).
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
        "--all-fields", action="store_true",
        help="Full inventory API field union plus the four model columns. "
             "See --list-fields --all-fields.",
    )
    # Pipeline-specific / shared args.
    parser.add_argument(
        "--model-page-size", type=int, default=fm.DEFAULT_PAGE_SIZE,
        help=f"Rows fetched per request during model lookup paging "
             f"(default: {fm.DEFAULT_PAGE_SIZE}). Exact-match queries "
             f"should rarely page, but this is exposed for parity.",
    )
    parser.add_argument(
        "--credentials-file", default=fpi.DEFAULT_CREDENTIALS_FILE,
        help=f"Path to .env file with APP_USERNAME, APP_PASSWORD, and "
             f"HOMESOURCE_BASE_URL (default: {fpi.DEFAULT_CREDENTIALS_FILE}).",
    )
    parser.add_argument(
        "--base-url", default=None,
        help="Override HOMESOURCE_BASE_URL from the credentials file.",
    )
    parser.add_argument(
        "--show-browser", action="store_true",
        help="Show the Chrome window instead of running headless.",
    )
    parser.add_argument(
        "--delay", type=float, default=0.25,
        help="Seconds to wait between fetches within each phase "
             "(default: 0.25).",
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

    in_fmt  = fpi._detect_format(args.input,  args.input_format)
    out_fmt = fpi._detect_format(args.output, args.output_format)

    # Validate input before launching Chrome.
    run_ids = fpi.load_run_ids(
        args.input, in_fmt, args.run_id_column, args.run_ids
    )
    if not run_ids:
        sys.stderr.write("ERROR: no run IDs found in input.\n")
        return 2

    # Load credentials and authenticate ONCE for both phases.
    creds = fpi.load_credentials(args.credentials_file)
    base_url = (args.base_url or creds["HOMESOURCE_BASE_URL"]).rstrip("/")

    session = fpi.build_authenticated_session(
        creds,
        base_url,
        headless=not args.show_browser,
    )

    # ------------------------------------------------------------------
    # Phase 1: physical inventory
    # ------------------------------------------------------------------
    if not args.quiet:
        sys.stderr.write(
            f"\nPhase 1: fetching {len(run_ids)} physical inventory run(s)\n"
        )

    inventory_rows: list[dict] = []
    inv_failures = 0
    total_runs = len(run_ids)

    for idx, rid in enumerate(run_ids, 1):
        if not args.quiet:
            sys.stderr.write(f"  [{idx}/{total_runs}] Fetching run {rid}... ")
            sys.stderr.flush()

        referer = (
            f"{base_url}/inventory/physical/active"
            f"?PhysicalInventoryRunId={rid}"
        )
        try:
            raw_rows = fpi.fetch_run(
                session, base_url, rid, referer, timeout=args.timeout
            )
            flat = fpi.flatten_run(raw_rows, rid)
            if flat:
                inventory_rows.extend(flat)
                if not args.quiet:
                    sys.stderr.write(f"{len(flat)} row(s)\n")
            else:
                inventory_rows.append({
                    "_source_run_id": rid,
                    "_error": "run found but has no inventory rows",
                })
                if not args.quiet:
                    sys.stderr.write("no rows\n")
        except Exception as e:
            inv_failures += 1
            inventory_rows.append({
                "_source_run_id": rid,
                "_error": f"{type(e).__name__}: {e}",
            })
            if not args.quiet:
                sys.stderr.write(f"FAILED: {e}\n")

        if args.delay and idx < total_runs:
            time.sleep(args.delay)

    # ------------------------------------------------------------------
    # Phase 2: unique non-blank ModelNumbers -> model lookup
    # ------------------------------------------------------------------
    seen: set[str] = set()
    unique_models: list[str] = []
    for row in inventory_rows:
        mn = row.get("ModelNumber")
        if mn is None or mn == "":
            continue
        key = str(mn)
        if key not in seen:
            seen.add(key)
            unique_models.append(key)

    if not args.quiet:
        sys.stderr.write(
            f"\nPhase 2: looking up {len(unique_models)} unique model(s)\n"
        )

    model_failures = 0
    if unique_models:
        model_referer = f"{base_url}/inventory/model"
        lookup, _model_errors, model_failures = build_model_lookup(
            session, base_url, unique_models,
            referer=model_referer,
            page_size=args.model_page_size,
            timeout=args.timeout,
            delay=args.delay,
            quiet=args.quiet,
        )
    else:
        lookup = {}

    # ------------------------------------------------------------------
    # Phase 3: join and emit
    # ------------------------------------------------------------------
    append_model_fields(inventory_rows, lookup)

    count = emit_joined(
        inventory_rows, args.output, out_fmt,
        all_fields=args.all_fields,
        quiet=args.quiet,
    )

    if not args.quiet:
        sys.stderr.write(
            f"\nDone. {count} row(s) written. "
            f"{total_runs - inv_failures}/{total_runs} run(s) succeeded"
            + (f", {inv_failures} failed" if inv_failures else "")
            + ". "
            f"{len(unique_models) - model_failures}/{len(unique_models)} "
            f"model lookup(s) succeeded"
            + (f", {model_failures} failed" if model_failures else "")
            + ".\n"
        )

    total_failures = inv_failures + model_failures
    if inv_failures == total_runs and total_runs > 0:
        return 2
    return 1 if total_failures else 0


def cli() -> None:
    """Console entry point when installed via pip (fetch-physical-inventory-with-model)."""
    raise SystemExit(main())


if __name__ == "__main__":
    cli()
