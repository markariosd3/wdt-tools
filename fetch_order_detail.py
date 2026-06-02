#!/usr/bin/env python3
"""
fetch_order_detail.py

Fetches all invoiced units for one or more HomeSource orders, including
fields not visible in the order view UI: InventoryId, serial number,
warehouse location, received date, last scan details, cost data, and more.

For open/partially-invoiced orders the script calls the fast JSON API
(/sales/orders/search/{OrderId}) and gets all fields.

For closed orders the site blocks the API and redirects to an invoice
HTML page. The script detects this automatically, uses the already-open
Selenium browser to navigate to /sales/invoices/{OrderId}, scrapes the
visible table rows, and emits what it can. Deep fields (InventoryId,
serial number, warehouse location, cost data) will be blank for closed
orders; a _source column identifies where the data came from.

Authentication is handled automatically via open_homesource.py (which
must sit in the same directory). The script drives a headless Chrome to
log in once, keeps it running for closed-order scraping, and hands the
session cookies to requests for fast HTTP fetching of open orders.

USAGE
-----
Provide one or more order IDs in any of these ways:

    1) CSV file with an OrderId column (configurable with
       --order-id-column; default "OrderId"):
            python fetch_order_detail.py -i orders.csv -o units.csv

    2) JSON file -- flat array of IDs or array of objects:
            python fetch_order_detail.py -i orders.json -o units.json

    3) Piped on stdin (auto-detected as CSV unless --input-format json):
            type orders.csv | python fetch_order_detail.py > units.csv
            echo [17667,20835] | python fetch_order_detail.py --input-format json

    4) Inline on the command line:
            python fetch_order_detail.py --order-ids 17667,20835 -o units.csv

OUTPUT FORMATS
--------------
    --output-format csv   (default)  one row per invoiced unit
    --output-format json             array of objects, same fields

Every output row includes:
    _source_order_id  -- which input order produced this row
    _source           -- "api" (full data) or "invoice_html" (closed order,
                         limited fields only)
    _error            -- populated only when a fetch fails

AUTHENTICATION
--------------
Credentials are read from:
    %USERPROFILE%\\credentials\\wdt-tools\\.env   (default)

This resolves to the current Windows user's home directory automatically,
so the same script works for any user without modification.
Override with --credentials-file if your .env lives somewhere else.

Required keys in the .env file:
    APP_USERNAME=yourusername
    APP_PASSWORD=yourpassword
    HOMESOURCE_BASE_URL=https://your-tenant.homesourcesystems.com

Chrome runs headless by default. Pass --show-browser to watch it log in
(useful when troubleshooting or if a CAPTCHA appears).

EXIT CODES
----------
    0   all orders fetched successfully
    1   some orders failed (others succeeded; check _error column)
    2   fatal error (bad credentials, no input, auth failure)

EXAMPLES
--------
    # One order, CSV to stdout
    python fetch_order_detail.py --order-ids 17667

    # Many orders, file in and out
    python fetch_order_detail.py -i orders.csv -o units.csv

    # JSON output piped into another script
    python fetch_order_detail.py -i orders.csv --output-format json ^
        | python enrich_units.py > enriched.json

    # Watch the browser (debugging)
    python fetch_order_detail.py --order-ids 17667 --show-browser

    # Resume an interrupted run
    python fetch_order_detail.py -i orders.csv -o units.csv ^
        --skip-existing units.csv

REQUIREMENTS
------------
    pip install -r requirements.txt
    open_homesource.py and homesource_common.py must be in the same directory.
    Chrome must be installed (Selenium 4.6+ manages chromedriver automatically).
"""

from __future__ import annotations

import csv
import json
import sys
import time
from pathlib import Path
from typing import Any

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

# Maps invoice HTML table data-field values to COLUMNS schema names.
INVOICE_HTML_FIELD_MAP = {
    "Manufacturer": "Manufacturer",
    "Model": "Model",
    "Description": "Description",
    "RoomFK": "RoomName",
    "Needed": "NeededString",
    "SalePrice": "SalePrice",
    "Qty": "Qty",
    "Taxable": "Taxable",
    "StorePickupLocationFK": "TruckName",
    "InvoicedDate": "InvoicedDate",
}


# ---------------------------------------------------------------------------
# Field schema
# ---------------------------------------------------------------------------
COLUMNS: list[str] = [
    # Provenance
    "_source_order_id", "_source", "_error",
    # Order/line identifiers
    "OrderItemId", "OrderFK", "InvoiceItemId", "BatchId", "InvoicedDate",
    "InvoicedBy", "CreationUser", "ShippingCustomerId_FK",
    "OriginalOrderItemId_FK", "ReturnItemId_FK",
    # Product info
    "Model", "Manufacturer", "Description",
    "ProductId", "GroupId", "MID_FK",
    # Pricing & tax
    "Qty", "Order", "Needed", "NeededString",
    "SalePrice", "SuggestedPrice", "OriginalUnitPrice",
    "InvoicedCost", "InvoicedSalespersonCost",
    "TaxAmount", "TaxRate", "Taxable", "IndividualTaxAmount",
    "OverrideTax", "ExcludeMiscTax", "MiscTaxAmount",
    "Jurisdiction_State", "Jurisdiction_Country",
    # Delivery & flags
    "DeliveryPickupTypeId_FK", "EstimatedDeliveryDate",
    "IsSerialized", "BuyingGroupQty",
    # Room
    "RoomFK", "RoomName", "RoomIsDefault",
    # Truck (TruckName will be "STORAGE" for storage orders)
    "TruckScheduleOrderItemId", "TruckScheduleOrderFk",
    "TruckId", "TruckName", "TruckShortName", "TruckDescription",
    "TruckColorCode", "TruckLocationId_FK",
    # Line note
    "LineNote_Id", "LineNote_Text", "LineNote_PostUser",
    "LineNote_CreatedAt", "LineNote_UpdatedAt",
    # Misc item (non-serialized lines like delivery charges)
    "MiscItem_Id", "MiscItem_Brand", "MiscItem_Model",
    "MiscItem_Description", "MiscItem_SalePrice", "MiscItem_Cost",
    "MiscItem_Taxable", "MiscItem_DeletedAt",
    # Physical unit (blank for closed orders scraped from HTML)
    "InventoryId", "InventoryModelId_FK",
    "MFGSerialNumber", "MFGRunNumber",
    "ScannedMFGSerialNumber", "ScannedMFGRunNumber",
    "Inv_Cost", "Inv_SalesPrice", "Inv_SalespersonCost",
    "Inv_ShippingCost", "Inv_AverageCost",
    "PurchaseOrderItemId_FK",
    "ReceivedDate", "Inv_InvoicedDate", "Inv_InvoiceItemId_FK",
    "Inv_OrderItemId_FK", "LocationId_FK", "WHSELocationId_FK",
    "SerialStatusId_FK", "InventoryStatus", "Paid", "NonSellable",
    "Inv_Notes", "Manifest",
    "LastScannedTime",
    "LastScanned_User", "LastScanned_UserId",
    "LastScanned_Location", "LastScanned_LocationName",
    "LastScanned_WHSELocation", "LastScanned_WHSELocationName",
    "LastScanned_ExpectedLocation", "LastScanned_ExpectedLocationName",
    "LastScanned_ExpectedWHSELocation", "LastScanned_ExpectedWHSELocationName",
    "ReferenceNumber",
    "COM_PostingAccountId_FK", "Inventory_PostingAccountId_FK",
    "Revenue_PostingAccountId_FK",
    "Inv_CreationUser", "Inv_PostUser",
    "Inv_CreatedAt", "Inv_DeletedAt",
    "is_allocated", "Age",
]


def column_catalog() -> hc.ColumnCatalog:
    return hc.ColumnCatalog(
        title="Order detail export",
        default_fields=COLUMNS,
        all_fields_fixed=COLUMNS,
    )


# ---------------------------------------------------------------------------
# Flattening helpers (for JSON API responses)
# ---------------------------------------------------------------------------
def _get(d: Any, *keys: str) -> Any:
    """Safe nested-dict get. Returns empty string for missing/None."""
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return ""
        cur = cur.get(k)
    return "" if cur is None else cur


def _line_fields(item: dict) -> dict:
    return {
        "OrderItemId":              _get(item, "OrderItemId"),
        "OrderFK":                  _get(item, "OrderFK"),
        "InvoiceItemId":            _get(item, "InvoiceItemId"),
        "BatchId":                  _get(item, "BatchId"),
        "InvoicedDate":             _get(item, "InvoicedDate"),
        "InvoicedBy":               _get(item, "invoicedCreationUserName"),
        "CreationUser":             _get(item, "CreationUser"),
        "ShippingCustomerId_FK":    _get(item, "ShippingCustomerId_FK"),
        "OriginalOrderItemId_FK":   _get(item, "OriginalOrderItemId_FK"),
        "ReturnItemId_FK":          _get(item, "ReturnItemId_FK"),
        "Model":                    _get(item, "Model"),
        "Manufacturer":             _get(item, "Manufacturer"),
        "Description":              _get(item, "Description"),
        "ProductId":                _get(item, "ProductId"),
        "GroupId":                  _get(item, "GroupId"),
        "MID_FK":                   _get(item, "MID_FK"),
        "Qty":                      _get(item, "Qty"),
        "Order":                    _get(item, "Order"),
        "Needed":                   _get(item, "Needed"),
        "NeededString":             _get(item, "NeededString"),
        "SalePrice":                _get(item, "SalePrice"),
        "SuggestedPrice":           _get(item, "SuggestedPrice"),
        "OriginalUnitPrice":        _get(item, "OriginalUnitPrice"),
        "InvoicedCost":             _get(item, "InvoicedCost"),
        "InvoicedSalespersonCost":  _get(item, "InvoicedSalespersonCost"),
        "TaxAmount":                _get(item, "TaxAmount"),
        "TaxRate":                  _get(item, "TaxRate"),
        "Taxable":                  _get(item, "Taxable"),
        "IndividualTaxAmount":      _get(item, "IndividualTaxAmount"),
        "OverrideTax":              _get(item, "OverrideTax"),
        "ExcludeMiscTax":           _get(item, "ExcludeMiscTax"),
        "MiscTaxAmount":            _get(item, "MiscTaxAmount"),
        "Jurisdiction_State":       _get(item, "Jurisdiction", "state"),
        "Jurisdiction_Country":     _get(item, "Jurisdiction", "country"),
        "DeliveryPickupTypeId_FK":  _get(item, "DeliveryPickupTypeId_FK"),
        "EstimatedDeliveryDate":    _get(item, "EstimatedDeliveryDate"),
        "IsSerialized":             _get(item, "IsSerialized"),
        "BuyingGroupQty":           _get(item, "BuyingGroupQty"),
        "RoomFK":                   _get(item, "RoomFK"),
        "RoomName":                 _get(item, "room", "Name"),
        "RoomIsDefault":            _get(item, "room", "IsDefault"),
        "TruckScheduleOrderItemId": _get(item, "truck_order_item", "TruckScheduleOrderItemId"),
        "TruckScheduleOrderFk":     _get(item, "truck_order_item", "TruckScheduleOrderFk"),
        "TruckId":                  _get(item, "truck_order_item", "truck", "TruckId"),
        "TruckName":                _get(item, "truck_order_item", "truck", "Name"),
        "TruckShortName":           _get(item, "truck_order_item", "truck", "ShortName"),
        "TruckDescription":         _get(item, "truck_order_item", "truck", "Description"),
        "TruckColorCode":           _get(item, "truck_order_item", "truck", "ColorCode"),
        "TruckLocationId_FK":       _get(item, "truck_order_item", "truck", "LocationId_FK"),
        "LineNote_Id":              _get(item, "line_note", "OrderItemNoteId"),
        "LineNote_Text":            _get(item, "line_note", "Note"),
        "LineNote_PostUser":        _get(item, "line_note", "PostUser"),
        "LineNote_CreatedAt":       _get(item, "line_note", "created_at"),
        "LineNote_UpdatedAt":       _get(item, "line_note", "updated_at"),
        "MiscItem_Id":              _get(item, "misc_item", "MiscItemId"),
        "MiscItem_Brand":           _get(item, "misc_item", "Brand"),
        "MiscItem_Model":           _get(item, "misc_item", "Model"),
        "MiscItem_Description":     _get(item, "misc_item", "Description"),
        "MiscItem_SalePrice":       _get(item, "misc_item", "SalePrice"),
        "MiscItem_Cost":            _get(item, "misc_item", "Cost"),
        "MiscItem_Taxable":         _get(item, "misc_item", "Taxable"),
        "MiscItem_DeletedAt":       _get(item, "misc_item", "deleted_at"),
    }


def _unit_fields(inv: dict) -> dict:
    return {
        "InventoryId":                          _get(inv, "InventoryId"),
        "InventoryModelId_FK":                  _get(inv, "InventoryModelId_FK"),
        "MFGSerialNumber":                      _get(inv, "MFGSerialNumber"),
        "MFGRunNumber":                         _get(inv, "MFGRunNumber"),
        "ScannedMFGSerialNumber":               _get(inv, "ScannedMFGSerialNumber"),
        "ScannedMFGRunNumber":                  _get(inv, "ScannedMFGRunNumber"),
        "Inv_Cost":                             _get(inv, "Cost"),
        "Inv_SalesPrice":                       _get(inv, "SalesPrice"),
        "Inv_SalespersonCost":                  _get(inv, "SalespersonCost"),
        "Inv_ShippingCost":                     _get(inv, "ShippingCost"),
        "Inv_AverageCost":                      _get(inv, "AverageCost"),
        "PurchaseOrderItemId_FK":               _get(inv, "PurchaseOrderItemId_FK"),
        "ReceivedDate":                         _get(inv, "ReceivedDate"),
        "Inv_InvoicedDate":                     _get(inv, "InvoicedDate"),
        "Inv_InvoiceItemId_FK":                 _get(inv, "InvoiceItemId_FK"),
        "Inv_OrderItemId_FK":                   _get(inv, "OrderItemId_FK"),
        "LocationId_FK":                        _get(inv, "LocationId_FK"),
        "WHSELocationId_FK":                    _get(inv, "WHSELocationId_FK"),
        "SerialStatusId_FK":                    _get(inv, "SerialStatusId_FK"),
        "InventoryStatus":                      _get(inv, "InventoryStatus"),
        "Paid":                                 _get(inv, "Paid"),
        "NonSellable":                          _get(inv, "NonSellable"),
        "Inv_Notes":                            _get(inv, "Notes"),
        "Manifest":                             _get(inv, "Manifest"),
        "LastScannedTime":                      _get(inv, "LastScannedTime"),
        "LastScanned_User":                     _get(inv, "LastScannedDetails", "User"),
        "LastScanned_UserId":                   _get(inv, "LastScannedDetails", "UserId"),
        "LastScanned_Location":                 _get(inv, "LastScannedDetails", "Location"),
        "LastScanned_LocationName":             _get(inv, "LastScannedDetails", "LocationName"),
        "LastScanned_WHSELocation":             _get(inv, "LastScannedDetails", "WHSELocation"),
        "LastScanned_WHSELocationName":         _get(inv, "LastScannedDetails", "WHSELocationName"),
        "LastScanned_ExpectedLocation":         _get(inv, "LastScannedDetails", "ExpectedLocation"),
        "LastScanned_ExpectedLocationName":     _get(inv, "LastScannedDetails", "ExpectedLocationName"),
        "LastScanned_ExpectedWHSELocation":     _get(inv, "LastScannedDetails", "ExpectedWHSELocation"),
        "LastScanned_ExpectedWHSELocationName": _get(inv, "LastScannedDetails", "ExpectedWHSELocationName"),
        "ReferenceNumber":                      _get(inv, "ReferenceNumber"),
        "COM_PostingAccountId_FK":              _get(inv, "COM_PostingAccountId_FK"),
        "Inventory_PostingAccountId_FK":        _get(inv, "Inventory_PostingAccountId_FK"),
        "Revenue_PostingAccountId_FK":          _get(inv, "Revenue_PostingAccountId_FK"),
        "Inv_CreationUser":                     _get(inv, "CreationUser"),
        "Inv_PostUser":                         _get(inv, "PostUser"),
        "Inv_CreatedAt":                        _get(inv, "created_at"),
        "Inv_DeletedAt":                        _get(inv, "deleted_at"),
        "is_allocated":                         _get(inv, "is_allocated"),
        "Age":                                  _get(inv, "Age"),
    }


def flatten_order(order_json: dict, source_order_id: str) -> list[dict]:
    """
    Convert one order's JSON into a list of unit-row dicts.
    One row per physical unit. Non-serialized lines (e.g. delivery
    charges) get one row with only line-level fields populated.
    """
    items = order_json.get("invoice_items") or []
    rows: list[dict] = []
    for item in items:
        line = _line_fields(item)
        units = item.get("invoiced_inventory") or []
        if not units:
            row = {col: "" for col in COLUMNS}
            row.update(line)
            row["_source_order_id"] = source_order_id
            row["_source"] = "api"
            rows.append(row)
        else:
            for inv in units:
                row = {col: "" for col in COLUMNS}
                row.update(line)
                row.update(_unit_fields(inv))
                row["_source_order_id"] = source_order_id
                row["_source"] = "api"
                rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Closed-order HTML scraper (Selenium)
# ---------------------------------------------------------------------------
def scrape_closed_order(
    driver: Any,
    base_url: str,
    order_id: str,
    page_timeout: float = 30.0,
) -> list[dict]:
    """
    Navigate to /sales/invoices/{order_id} and scrape the visible line-item
    table. Returns a list of row dicts using the same COLUMNS schema.
    Deep fields (InventoryId, serial number, cost, etc.) will be blank.
    _source is set to "invoice_html" on every row.

    The invoice page is a Kendo grid with these columns (confirmed from
    the live thead):
        #(hidden) | MFR | Model Number | Description | Room | Needed |
        Sale Price | Qty | Ext. Price | Txbl | Delivery | Delivered | Action

    Column mapping is built dynamically from the <th data-field="...">
    attributes so it stays correct even if columns are reordered or hidden.

    data-field values -> our schema:
        Manufacturer      -> Manufacturer
        Model             -> Model
        Description       -> Description
        RoomFK            -> RoomName  (text content is the room name)
        Needed            -> NeededString
        SalePrice         -> SalePrice
        Qty               -> Qty
        Taxable           -> Taxable
        StorePickupLocationFK -> TruckName  (Delivery type column)
        InvoicedDate      -> InvoicedDate
    """
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait

    url = f"{base_url}/sales/invoices/{order_id}"
    driver.get(url)

    # Wait for the invoice table body to have at least one cell
    try:
        WebDriverWait(driver, page_timeout).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "table tbody tr td"))
        )
    except Exception:
        return []

    # Build a column index map from the <th data-field> attributes.
    # This maps data-field value -> td index in each row, accounting
    # for the hidden # column and any other hidden/reordered columns.
    # We use the DOM order of <th> elements (including hidden ones).
    ths = driver.find_elements(By.CSS_SELECTOR, "table thead tr th")
    # data-field -> td cell index (0-based DOM position)
    field_to_idx: dict[str, int] = {}
    for i, th in enumerate(ths):
        field = th.get_attribute("data-field") or ""
        if field:
            field_to_idx[field] = i

    rows: list[dict] = []
    trs = driver.find_elements(By.CSS_SELECTOR, "table tbody tr")

    for tr in trs:
        tds = tr.find_elements(By.TAG_NAME, "td")
        if len(tds) < 4:
            continue
        cells = [td.text.strip() for td in tds]
        rows.append(
            invoice_row_from_cells(order_id, field_to_idx, cells)
        )

    return rows


def invoice_row_from_cells(
    order_id: str,
    field_to_idx: dict[str, int],
    cells: list[str],
) -> dict:
    """
    Build one invoice_html row from table cell text (testable without Selenium).
    """
    row = {col: "" for col in COLUMNS}
    row["_source_order_id"] = order_id
    row["_source"] = "invoice_html"
    row["OrderFK"] = order_id

    def cell(idx: int) -> str:
        try:
            return cells[idx]
        except IndexError:
            return ""

    for data_field, schema_field in INVOICE_HTML_FIELD_MAP.items():
        idx = field_to_idx.get(data_field)
        if idx is not None:
            row[schema_field] = cell(idx)

    return row


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
) -> tuple[Any, requests.Session]:
    """Return (driver, session); caller must quit driver when done."""
    try:
        return hc.build_authenticated_session(
            creds,
            base_url,
            headless,
            keep_driver=True,
            login_timeout=login_timeout,
            extra_session_headers={"referer": f"{base_url}/sales/orders"},
        )
    except ImportError as e:
        sys.stderr.write(f"ERROR: {e}\n")
        sys.exit(2)
    except hc.LoginError as e:
        sys.stderr.write(f"ERROR: {e}\n")
        sys.exit(2)


# ---------------------------------------------------------------------------
# Fetching (JSON API -- open/partially-invoiced orders)
# ---------------------------------------------------------------------------
class ClosedOrderError(Exception):
    """Raised when the site returns an empty body for a closed order."""
    pass


def fetch_order(
    session: requests.Session,
    base_url: str,
    order_id: str,
    timeout: float = 30.0,
) -> dict:
    """Fetch one order via the JSON API. Raises ClosedOrderError if closed."""
    url = f"{base_url}/sales/orders/search/{order_id}"
    resp = session.get(url, timeout=timeout)
    resp.raise_for_status()
    ctype = resp.headers.get("content-type", "")

    # Closed orders return an empty 200 body
    if not resp.text.strip():
        raise ClosedOrderError(f"order {order_id} is closed (empty response)")

    if "json" not in ctype.lower():
        # Non-empty, non-JSON -- likely a real session expiry
        snippet = resp.text[:200].replace("\n", " ")
        raise RuntimeError(
            f"Non-JSON response (content-type={ctype!r}); "
            f"session may have expired. Body: {snippet}"
        )
    return resp.json()


_detect_format = hc.detect_format


def load_order_ids(
    source: str | None,
    fmt: str,
    column: str,
    inline_ids: str | None,
) -> list[str]:
    """Return a deduplicated, order-preserving list of order ID strings."""
    return hc.load_ids_from_input(
        source,
        fmt,
        column,
        inline_ids,
        json_key_candidates=(column, "OrderId", "order_id", "orderId", "Order", "Id"),
    )


def load_skip_set(path: str | None) -> set[str]:
    """Return the set of _source_order_id values already in a prior output."""
    if not path or not Path(path).exists():
        return set()
    skip: set[str] = set()
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames and "_source_order_id" in reader.fieldnames:
                for row in reader:
                    val = (row.get("_source_order_id") or "").strip()
                    if val:
                        skip.add(val)
                return skip
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        for r in (data if isinstance(data, list) else []):
            if isinstance(r, dict):
                val = str(r.get("_source_order_id") or "").strip()
                if val:
                    skip.add(val)
    except Exception as e:
        sys.stderr.write(f"WARN: could not read skip file {path}: {e}\n")
    return skip


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
def emit_rows(rows: list[dict], out_path: str | None, fmt: str) -> int:
    """Write rows to a file or stdout. Returns the count written."""
    return hc.emit_tabular_rows(rows, out_path, fmt, COLUMNS)


CLI_HELP_EXAMPLES = """
Examples:
  # One order -> spreadsheet
  fetch-order-detail --order-ids 17667 -o units.csv

  # Many orders from a CSV list
  fetch-order-detail -i orders.csv -o units.csv

  # Resume a long run (skip orders already in the file)
  fetch-order-detail -i orders.csv -o units.csv --skip-existing units.csv

  # Troubleshoot login (visible Chrome)
  fetch-order-detail --order-ids 17667 --show-browser -o units.csv

  # Preview all export columns (same list every time)
  fetch-order-detail --list-fields
  fetch-order-detail --list-fields --all-fields

notes:
  Open orders: richest data (_source=api).
  Closed orders: invoice-page data only (_source=invoice_html)—serials/costs
  may be blank; that is expected.
"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = hc.create_fetch_parser(
        prog="fetch-order-detail",
        description=(
            "Export one row per invoiced unit for each order ID. Best for open "
            "orders (full detail). Closed orders still export what the invoice "
            "page shows—use -o to save a file for Excel."
        ),
        examples=CLI_HELP_EXAMPLES,
    )
    parser.add_argument(
        "-i", "--input", default=None,
        help="Input file (CSV or JSON). Omit or use '-' for stdin.",
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
        "--order-id-column", default="OrderId",
        help="Column/key name to read order IDs from (default: OrderId).",
    )
    parser.add_argument(
        "--order-ids", default=None,
        help="Comma-separated list of order IDs, bypasses --input.",
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
        "--skip-existing", default=None,
        help="Path to a prior output file. Orders already in its "
             "_source_order_id column will be skipped.",
    )
    parser.add_argument(
        "--delay", type=float, default=0.25,
        help="Seconds to wait between requests (default: 0.25).",
    )
    parser.add_argument(
        "--timeout", type=float, default=30.0,
        help="Per-request timeout in seconds (default: 30).",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="Suppress progress output on stderr.",
    )
    parser.add_argument(
        "--all-fields", action="store_true",
        help="No effect on export (full column set is always written). "
             "Use with --list-fields to print the complete column list.",
    )
    hc.add_list_fields_argument(parser)
    hc.add_version_argument(parser)
    args = parser.parse_args(argv)

    if args.list_fields:
        return hc.print_column_catalog(column_catalog(), all_fields=args.all_fields)

    in_fmt  = _detect_format(args.input,  args.input_format)
    out_fmt = _detect_format(args.output, args.output_format)

    # Validate input before launching Chrome
    order_ids = load_order_ids(
        args.input, in_fmt, args.order_id_column, args.order_ids
    )
    if not order_ids:
        sys.stderr.write("ERROR: no order IDs found in input.\n")
        return 2

    skip = load_skip_set(args.skip_existing)
    if skip and not args.quiet:
        sys.stderr.write(
            f"Skipping {len(skip)} order(s) already present in {args.skip_existing}\n"
        )
    to_fetch = [oid for oid in order_ids if oid not in skip]
    if not to_fetch:
        sys.stderr.write("Nothing to do: all orders already in skip set.\n")
        emit_rows([], args.output, out_fmt)
        return 0

    # Load credentials and authenticate -- driver stays alive for closed orders
    creds = load_credentials(args.credentials_file)
    base_url = (args.base_url or creds["HOMESOURCE_BASE_URL"]).rstrip("/")

    driver, session = build_authenticated_session(
        creds,
        base_url,
        headless=not args.show_browser,
    )

    # Fetch each order
    all_rows: list[dict] = []
    failures = 0
    closed_scraped = 0
    total = len(to_fetch)

    try:
        for idx, oid in enumerate(to_fetch, 1):
            if not args.quiet:
                sys.stderr.write(f"[{idx}/{total}] Fetching order {oid}... ")
                sys.stderr.flush()
            try:
                data = fetch_order(session, base_url, oid, timeout=args.timeout)
                rows = flatten_order(data, oid)
                if rows:
                    all_rows.extend(rows)
                    if not args.quiet:
                        sys.stderr.write(f"{len(rows)} unit row(s)\n")
                else:
                    placeholder = {col: "" for col in COLUMNS}
                    placeholder["_source_order_id"] = oid
                    placeholder["_source"] = "api"
                    placeholder["_error"] = "order found but has no invoiced units"
                    all_rows.append(placeholder)
                    if not args.quiet:
                        sys.stderr.write("no invoiced units\n")

            except ClosedOrderError:
                # Closed order -- fall back to Selenium HTML scraping
                if not args.quiet:
                    sys.stderr.write("closed, scraping invoice HTML... ")
                    sys.stderr.flush()
                try:
                    rows = scrape_closed_order(
                        driver, base_url, oid, page_timeout=args.timeout
                    )
                    if rows:
                        all_rows.extend(rows)
                        closed_scraped += 1
                        if not args.quiet:
                            sys.stderr.write(f"{len(rows)} row(s) from HTML\n")
                    else:
                        placeholder = {col: "" for col in COLUMNS}
                        placeholder["_source_order_id"] = oid
                        placeholder["_source"] = "invoice_html"
                        placeholder["_error"] = "closed order invoice page had no rows"
                        all_rows.append(placeholder)
                        if not args.quiet:
                            sys.stderr.write("no rows found on invoice page\n")
                except Exception as scrape_err:
                    failures += 1
                    err_row = {col: "" for col in COLUMNS}
                    err_row["_source_order_id"] = oid
                    err_row["_source"] = "invoice_html"
                    err_row["_error"] = f"scrape failed: {type(scrape_err).__name__}: {scrape_err}"
                    all_rows.append(err_row)
                    if not args.quiet:
                        sys.stderr.write(f"FAILED: {scrape_err}\n")

            except Exception as e:
                failures += 1
                err_row = {col: "" for col in COLUMNS}
                err_row["_source_order_id"] = oid
                err_row["_source"] = ""
                err_row["_error"] = f"{type(e).__name__}: {e}"
                all_rows.append(err_row)
                if not args.quiet:
                    sys.stderr.write(f"FAILED: {e}\n")

            if args.delay and idx < total:
                time.sleep(args.delay)

    finally:
        # Always close the browser, even if something went wrong mid-run
        try:
            driver.quit()
        except Exception:
            pass

    count = emit_rows(all_rows, args.output, out_fmt)
    if not args.quiet:
        sys.stderr.write(
            f"\nDone. {count} row(s) written. "
            f"{total - failures}/{total} order(s) succeeded"
            + (f", {closed_scraped} closed (HTML scraped)" if closed_scraped else "")
            + (f", {failures} failed" if failures else "")
            + ".\n"
        )

    if failures == total:
        return 2
    return 1 if failures else 0


def cli() -> None:
    """Console entry point when installed via pip (fetch-order-detail)."""
    raise SystemExit(main())


if __name__ == "__main__":
    cli()
