"""
Shared helpers for HomeSource export CLI tools.

Import this module from fetch scripts; it is not meant to be run directly.
Pure functions here are covered by unit tests (no Chrome or live API calls).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass, field
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Any, Iterable, Sequence

# HomeSource (Laravel) sets this cookie name after a successful web login.
LOGIN_SESSION_COOKIE_NAME = "laravel_session"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

REQUIRED_CREDENTIAL_KEYS = ("APP_USERNAME", "APP_PASSWORD", "HOMESOURCE_BASE_URL")

DEFAULT_CREDENTIALS_FILE = str(
    Path.home() / "credentials" / "wdt-tools" / ".env"
)

_PROJECT_ROOT = Path(__file__).resolve().parent


class HomeSourceError(Exception):
    """Base error for shared HomeSource helpers."""


class CredentialsError(HomeSourceError):
    """Credentials file missing or incomplete."""


class LoginError(HomeSourceError):
    """Selenium login or session handoff failed."""


def read_project_version() -> str:
    """
    Return package version.

    Uses installed distribution metadata after ``pip install``; falls back to
    the VERSION file next to the source tree when running from a git checkout.
    """
    try:
        return importlib_metadata.version("wdt-tools")
    except importlib_metadata.PackageNotFoundError:
        version_file = _PROJECT_ROOT / "VERSION"
        return version_file.read_text(encoding="utf-8").strip()


def load_credentials(path: str) -> dict[str, str]:
    """
    Parse a simple .env file (KEY=value lines).

    Raises CredentialsError if the file is missing or required keys are empty.
    """
    p = Path(path)
    if not p.exists():
        raise CredentialsError(
            f"credentials file not found: {path}\n"
            f"It must contain APP_USERNAME, APP_PASSWORD, and "
            f"HOMESOURCE_BASE_URL lines."
        )
    out: dict[str, str] = {}
    for line in p.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    missing = [k for k in REQUIRED_CREDENTIAL_KEYS if not out.get(k)]
    if missing:
        raise CredentialsError(
            f"{path} is missing required key(s): {', '.join(missing)}"
        )
    return out


def flatten_record(obj: Any, prefix: str = "") -> dict[str, Any]:
    """
    Flatten a nested dict into dotted keys.
    Lists are JSON-encoded; None becomes "".
    """
    out: dict[str, Any] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v, dict):
                out.update(flatten_record(v, key))
            elif isinstance(v, list):
                out[key] = json.dumps(v, default=str)
            else:
                out[key] = "" if v is None else v
    else:
        out[prefix or "value"] = obj
    return out


def extract_kendo_rows(payload: Any) -> tuple[list[Any], int | None]:
    """
    Normalize a Kendo showAll response into (rows, total).

    Handles plain list, {data, total}, {Data, Total}, or a single object.
    """
    if isinstance(payload, list):
        return payload, None
    if isinstance(payload, dict):
        for data_key, total_key in (("data", "total"), ("Data", "Total")):
            if data_key in payload and isinstance(payload[data_key], list):
                total = payload.get(total_key)
                try:
                    total = int(total) if total is not None else None
                except (TypeError, ValueError):
                    total = None
                return payload[data_key], total
        return [payload], None
    return [], None


def detect_format(path: str | None, explicit: str | None) -> str:
    """Return 'csv' or 'json' from explicit flag or file extension."""
    if explicit:
        return explicit
    if path:
        ext = Path(path).suffix.lower()
        if ext == ".json":
            return "json"
        if ext in (".csv", ".tsv", ".txt"):
            return "csv"
    return "csv"


def dedupe(items: Iterable[str]) -> list[str]:
    """Deduplicate while preserving first-seen order."""
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        if it not in seen:
            seen.add(it)
            out.append(it)
    return out


def load_ids_from_input(
    source: str | None,
    fmt: str,
    column: str,
    inline: str | None,
    *,
    json_key_candidates: Sequence[str],
) -> list[str]:
    """
    Load ID strings from inline CSV list, a file, or stdin.

    json_key_candidates: keys tried on JSON objects (column name first).
    """
    ids: list[str] = []

    if inline:
        for part in inline.split(","):
            part = part.strip()
            if part:
                ids.append(part)
        return dedupe(ids)

    text = (
        Path(source).read_text(encoding="utf-8-sig")
        if (source and source != "-")
        else sys.stdin.read()
    )
    if not text.strip():
        return []

    if fmt == "json":
        data = json.loads(text)
        entries = data if isinstance(data, list) else [data]
        for entry in entries:
            if isinstance(entry, (int, str)):
                ids.append(str(entry).strip())
            elif isinstance(entry, dict):
                for key in json_key_candidates:
                    if key in entry and entry[key] is not None:
                        ids.append(str(entry[key]).strip())
                        break
    else:
        rows = list(csv.reader(text.splitlines()))
        if not rows:
            return []
        header = rows[0]
        if column in header:
            idx = header.index(column)
            for row in rows[1:]:
                if len(row) > idx and row[idx].strip():
                    ids.append(row[idx].strip())
        else:
            for row in rows:
                if row and row[0].strip():
                    ids.append(row[0].strip())

    return dedupe(i for i in ids if i)


def build_all_columns(
    rows: list[dict],
    provenance_columns: Sequence[str],
) -> list[str]:
    """Full column union: provenance first, then keys in first-seen order."""
    seen: set[str] = set(provenance_columns)
    cols: list[str] = list(provenance_columns)
    for r in rows:
        for k in r.keys():
            if k not in seen:
                seen.add(k)
                cols.append(k)
    return cols


def build_curated_columns(
    rows: list[dict],
    provenance_columns: Sequence[str],
    default_fields: Sequence[str],
    *,
    quiet: bool = False,
    script_label: str = "curated",
) -> list[str]:
    """Return default_fields plus _error; warn if API keys may have drifted."""
    columns = list(default_fields)
    if "_error" not in columns:
        columns.append("_error")

    if not quiet:
        present = {k for r in rows for k in r.keys()}
        expected = [c for c in default_fields if c not in provenance_columns]
        matched = [c for c in expected if c in present]
        if expected and not matched:
            sys.stderr.write(
                f"WARN: none of the {script_label} fields were found in the "
                "response. The endpoint's key names may differ from what was "
                "expected:\n"
                f"      {', '.join(expected)}\n"
                "      Run with --all-fields to see actual field names, then "
                "update DEFAULT_FIELDS in the fetch script.\n"
            )
        elif len(matched) < len(expected):
            missing = [c for c in expected if c not in present]
            sys.stderr.write(
                f"WARN: some {script_label} fields never appeared in the "
                f"response (written as blank columns): {', '.join(missing)}\n"
            )

    return columns


def emit_tabular_rows(
    rows: list[dict],
    out_path: str | None,
    fmt: str,
    columns: Sequence[str],
) -> int:
    """Write rows as CSV or JSON to a file or stdout. Returns count written."""
    if fmt == "json":
        projected = [{c: r.get(c, "") for c in columns} for r in rows]
        text = json.dumps(projected, indent=2, default=str)
        if out_path and out_path != "-":
            Path(out_path).write_text(text, encoding="utf-8")
        else:
            sys.stdout.write(text + "\n")
        return len(projected)

    if out_path and out_path != "-":
        fh = open(out_path, "w", encoding="utf-8", newline="")
        close_after = True
    else:
        fh = sys.stdout
        close_after = False
    try:
        writer = csv.DictWriter(fh, fieldnames=list(columns), extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
    finally:
        if close_after:
            fh.close()
    return len(rows)


def emit_curated_rows(
    rows: list[dict],
    out_path: str | None,
    fmt: str,
    *,
    provenance_columns: Sequence[str],
    default_fields: Sequence[str],
    all_fields: bool = False,
    quiet: bool = False,
    script_label: str = "curated",
) -> int:
    """Emit rows using curated or full dynamic columns."""
    columns = (
        build_all_columns(rows, provenance_columns)
        if all_fields
        else build_curated_columns(
            rows,
            provenance_columns,
            default_fields,
            quiet=quiet,
            script_label=script_label,
        )
    )
    return emit_tabular_rows(rows, out_path, fmt, columns)


def build_authenticated_session(
    creds: dict[str, str],
    base_url: str,
    headless: bool,
    *,
    keep_driver: bool = False,
    login_timeout: float = 30.0,
    extra_session_headers: dict[str, str] | None = None,
):
    """
    Log in via Selenium, copy cookies into requests.Session.

    If keep_driver is False, closes Chrome and returns Session only.
    If keep_driver is True, returns (driver, session); caller must quit driver.

    Raises LoginError on failure. Raises ImportError if selenium is missing.
    """
    try:
        import requests
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.support.ui import WebDriverWait
    except ImportError as e:
        raise ImportError(
            "selenium and requests are required. Run: pip install -r requirements.txt"
        ) from e

    try:
        from open_homesource import login
    except ImportError as e:
        raise LoginError(
            f"could not import open_homesource: {e}. "
            "open_homesource.py must be in the same directory as the fetch scripts."
        ) from e

    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--window-size=1280,900")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument(f"user-agent={USER_AGENT}")

    sys.stderr.write("Starting Chrome and logging in to HomeSource...\n")
    driver = webdriver.Chrome(options=opts)
    cookies: list[dict] = []
    try:
        login(
            driver,
            creds["APP_USERNAME"],
            creds["APP_PASSWORD"],
            base_url,
        )

        def _logged_in(d) -> bool:
            if "/login" in (d.current_url or ""):
                return False
            return any(
                c["name"] == LOGIN_SESSION_COOKIE_NAME for c in d.get_cookies()
            )

        WebDriverWait(driver, login_timeout).until(_logged_in)
        cookies = driver.get_cookies()
    except Exception as e:
        try:
            driver.quit()
        except Exception:
            pass
        raise LoginError(f"login failed: {e}") from e

    if not cookies:
        try:
            driver.quit()
        except Exception:
            pass
        raise LoginError("no cookies after login")

    domain_host = base_url.split("://", 1)[-1].split("/", 1)[0]
    session = requests.Session()
    for c in cookies:
        domain = (c.get("domain") or domain_host).lstrip(".")
        session.cookies.set(
            c["name"],
            c["value"],
            domain=domain,
            path=c.get("path", "/"),
        )
    headers = {
        "accept": "*/*",
        "accept-language": "en-US,en;q=0.9",
        "user-agent": USER_AGENT,
        "x-requested-with": "XMLHttpRequest",
    }
    if extra_session_headers:
        headers.update(extra_session_headers)
    session.headers.update(headers)

    sys.stderr.write(f"Login successful. {len(cookies)} cookies captured.\n")

    if keep_driver:
        return driver, session

    try:
        driver.quit()
    except Exception:
        pass
    return session


def add_version_argument(parser) -> None:
    """Register --version on an argparse parser."""
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {read_project_version()}",
    )


COLUMNS_HELP_BLURB = """
columns (preview without fetching data):
  --list-fields                 default spreadsheet columns
  --list-fields --all-fields    full --all-fields export guide
"""


# Shared footer for fetch script --help / -h output.
CLI_HELP_FOOTER = """
more help:
  User guide (no coding):  see docs/GETTING_STARTED.md in the repo
  Developer guide:         see docs/FOR_DEVELOPERS.md

credentials:
  Default .env file:
    Windows:  %USERPROFILE%\\credentials\\wdt-tools\\.env
    macOS/Linux:  ~/credentials/wdt-tools/.env
  Required keys: APP_USERNAME, APP_PASSWORD, HOMESOURCE_BASE_URL
  Override path with --credentials-file

output:
  Tabular data -> stdout or -o/--output file (CSV by default)
  Progress and errors -> stderr

exit codes:
  0  all items fetched successfully
  1  some items failed (check _error column in output)
  2  fatal error (missing credentials, no input, login failure)
"""


def _help_formatter_class():
    try:
        from rich_argparse import RichHelpFormatter

        return RichHelpFormatter
    except ImportError:
        return argparse.RawDescriptionHelpFormatter


def create_fetch_parser(
    prog: str,
    description: str,
    examples: str,
    *,
    include_columns_blurb: bool = True,
) -> argparse.ArgumentParser:
    """
    Build an ArgumentParser with description, examples, and shared footer.

    Uses RichHelpFormatter when ``rich-argparse`` is installed (colorized -h).
  """
    parts = []
    if include_columns_blurb:
        parts.append(COLUMNS_HELP_BLURB.strip())
    parts.append(examples.rstrip())
    parts.append(CLI_HELP_FOOTER.strip())
    epilog = "\n\n".join(parts)
    return argparse.ArgumentParser(
        prog=prog,
        description=description,
        epilog=epilog,
        formatter_class=_help_formatter_class(),
    )


def add_list_fields_argument(parser: argparse.ArgumentParser) -> None:
    """Register --list-fields (use with --all-fields for full export columns)."""
    parser.add_argument(
        "--list-fields",
        action="store_true",
        help="Print output column names and exit (add --all-fields for full export mode).",
    )


@dataclass(frozen=True)
class ColumnCatalog:
    """Describes CSV/JSON columns for --list-fields."""

    title: str
    default_fields: Sequence[str]
    # When set, --all-fields mode writes exactly this fixed list (order detail).
    all_fields_fixed: Sequence[str] | None = None
    # Always appended after inventory columns (joined pipeline).
    appended_fields: Sequence[str] = field(default_factory=tuple)
    # Example extra API keys users may see with --all-fields (dynamic endpoints).
    all_fields_extra_hints: Sequence[str] = field(default_factory=tuple)


def _curated_with_error(fields: Sequence[str]) -> list[str]:
    cols = list(fields)
    if "_error" not in cols:
        cols.append("_error")
    return cols


def _rich_available() -> bool:
    try:
        import rich  # noqa: F401

        return True
    except ImportError:
        return False


def _print_field_table(title: str, fields: Sequence[str], *, style: str = "cyan") -> None:
    if _rich_available():
        from rich import box
        from rich.console import Console
        from rich.table import Table

        console = Console()
        table = Table(
            title=title,
            show_header=True,
            header_style="bold magenta",
            title_style="bold yellow",
            box=box.SIMPLE,  # ASCII-friendly for Windows terminals
        )
        table.add_column("#", style="dim", width=5, justify="right")
        table.add_column("Column name", style=style)
        for idx, name in enumerate(fields, 1):
            table.add_row(str(idx), name)
        console.print(table)
        return

    print(title)
    print("-" * len(title))
    for idx, name in enumerate(fields, 1):
        print(f"  {idx:3}  {name}")
    print()


def print_column_catalog(catalog: ColumnCatalog, *, all_fields: bool) -> int:
    """
    Print a colorized column guide to stdout and return exit code 0.

    ``all_fields=False`` -> default curated columns.
    ``all_fields=True``  -> full export mode (fixed list or dynamic explanation).
    """
    if _rich_available():
        from rich.console import Console

        out = Console()

        def say(text: str = "") -> None:
            out.print(text)

    else:

        def say(text: str = "") -> None:
            if not text:
                print()
                return
            plain = text
            for tag in (
                "[bold]", "[/bold]", "[dim]", "[/dim]", "[cyan]", "[/cyan]",
                "[bold cyan]", "[/bold cyan]", "[bold yellow]", "[/bold yellow]",
            ):
                plain = plain.replace(tag, "")
            print(plain)

    say()
    say(f"[bold cyan]{catalog.title}[/bold cyan]" if _rich_available() else catalog.title)
    if not _rich_available():
        print("=" * len(catalog.title))
    say()

    if not all_fields:
        default = _curated_with_error(catalog.default_fields)
        for col in catalog.appended_fields:
            if col not in default:
                default.append(col)
        _print_field_table(
            f"Default columns ({len(default)} - used without --all-fields)",
            default,
            style="green",
        )
        say(
            "\n[dim]Tip: add [bold]--all-fields[/bold] to your export command for "
            "every field the API returns, or run "
            "[bold]--list-fields --all-fields[/bold] now to preview that mode.[/dim]\n"
            if _rich_available()
            else (
                "\nTip: run with --all-fields on your export, or "
                "--list-fields --all-fields here.\n"
            )
        )
        return 0

    if catalog.all_fields_fixed is not None:
        fixed = list(catalog.all_fields_fixed)
        _print_field_table(
            f"All columns ({len(fixed)} - full export every time)",
            fixed,
            style="cyan",
        )
        say(
            "\n[dim]Exports always include every column below; "
            "[bold]--all-fields[/bold] is optional and shows the same list.[/dim]\n"
            if _rich_available()
            else "\nThis command always exports every column listed above.\n"
        )
        return 0

    default = _curated_with_error(catalog.default_fields)
    _print_field_table(
        f"Curated columns ({len(default)} - subset of --all-fields)",
        default,
        style="green",
    )

    appended = list(catalog.appended_fields)
    if appended:
        say()
        _print_field_table(
            f"Always appended ({len(appended)})",
            appended,
            style="yellow",
        )

    say()
    if _rich_available():
        say("[bold yellow]--all-fields mode[/bold yellow]")
    else:
        say("--all-fields mode")
    say(
        "Writes every key returned by HomeSource for each row. "
        "Headers are the union of all keys seen (nested objects use dotted names)."
    )
    say(
        "The exact column list depends on your tenant; "
        "run a small export with --all-fields -o sample.csv to see headers in Excel."
    )

    if catalog.all_fields_extra_hints:
        say()
        say("Examples of extra columns you may see:" if not _rich_available()
            else "[bold]Examples of extra columns you may see:[/bold]")
        for hint in catalog.all_fields_extra_hints:
            say(f"  [cyan]•[/cyan] {hint}" if _rich_available() else f"  - {hint}")
    say()
    return 0
