# Getting started (no coding experience required)

**WDT Tools** (“Warehouse Duct Tape”) is a small set of commands that log into
your company’s **HomeSource** website the same way you do in Chrome, then
download data into a **spreadsheet file** (CSV) you can open in Excel.

You are not changing HomeSource. You are exporting a copy of data you already
have permission to see—faster than clicking through screens row by row.

> **Not made by HomeSource Systems.** These are independent tools. If something
> breaks after a HomeSource update, check for a new version of `wdt-tools` or
> ask whoever maintains this project in your group.

---

## Pick the right command

| I want to… | Use this command | You’ll need… |
|------------|------------------|--------------|
| Download every scan line from a **physical inventory run** | `fetch-physical-inventory` | One or more **Run IDs** (e.g. `641`) |
| Download **model catalog** info (descriptions, on-hand, etc.) | `fetch-model` | **Model numbers** (e.g. `VBW24PNLS`) |
| Download **invoiced units** on sales orders (serials, costs when available) | `fetch-order-detail` | **Order IDs** (e.g. `17667`) |
| Inventory run **plus** manufacturer, category, description, color on each row | `fetch-physical-inventory-with-model` | **Run IDs** |

Still unsure? Ask your warehouse or office lead which ID you have—they usually
know whether you’re looking at a “run,” a “model,” or an “order.”

---

## What you need on your computer

1. **Google Chrome** (the same browser you use for HomeSource).
2. **Python 3.10 or newer** — free from [python.org](https://www.python.org/downloads/).
   - On Windows: during install, check **“Add python.exe to PATH”**.
3. Your **HomeSource login** (email + password).
4. Your **tenant URL** — the address in the browser when you’re logged in, e.g.
   `https://your-company.homesourcesystems.com` (no `/login` at the end).

---

## One-time setup (about 10 minutes)

### Step 1 — Install the tools

Open **Command Prompt** or **PowerShell** and run:

```bash
pip install wdt-tools
```

If that fails, try:

```bash
python -m pip install wdt-tools
```

### Step 2 — Save your login (password file)

Create a folder and file (adjust if your IT team uses a different location):

**Windows**

```
C:\Users\YOUR_WINDOWS_NAME\credentials\wdt-tools\.env
```

**Mac / Linux**

```
~/credentials/wdt-tools/.env
```

Open `.env` in Notepad and paste (with **your** real values):

```env
APP_USERNAME=you@company.com
APP_PASSWORD=your-password-here
HOMESOURCE_BASE_URL=https://your-company.homesourcesystems.com
```

Save the file. **Never email this file** or put it in a shared drive everyone can browse.

### Step 3 — Try one export

Example: physical inventory run `641` into a file on your Desktop:

```bash
fetch-physical-inventory --run-ids 641 -o "%USERPROFILE%\Desktop\inventory.csv"
```

When it finishes, open `inventory.csv` in Excel.

---

## How a run feels

1. A **Chrome window may flash** (usually invisible). The tool logs in once.
2. **Text scrolls** in the black window—that’s progress, not an error.
3. A **`.csv` file** appears where you used `-o`.
4. If something failed for one ID, the spreadsheet still has a row with **`_error`**
   explaining that line—open the file and filter that column.

---

## Commands you’ll use every day

### Physical inventory

```bash
fetch-physical-inventory --run-ids 641 -o inventory.csv
```

Several runs at once:

```bash
fetch-physical-inventory --run-ids 641,642,650 -o inventory.csv
```

### Inventory + extra model columns (most popular “duct tape” join)

```bash
fetch-physical-inventory-with-model --run-ids 641 -o joined.csv
```

### Models

```bash
fetch-model --models VBW24PNLS -o model.csv
```

### Orders

```bash
fetch-order-detail --order-ids 17667 -o units.csv
```

---

## Built-in help (always available)

Every command can explain itself:

```bash
fetch-physical-inventory -h
fetch-model --help
```

That prints **colorized** usage, **examples**, and how to preview columns.

### See column names before you export

```bash
# Default spreadsheet columns (numbered table)
fetch-physical-inventory --list-fields

# What --all-fields means (full API export guide)
fetch-physical-inventory --list-fields --all-fields
```

Same flags work on `fetch-model`, `fetch-order-detail`, and
`fetch-physical-inventory-with-model`.

---

## When something goes wrong

| What you see | What to try |
|--------------|-------------|
| `credentials file not found` | Create the `.env` file from Step 2 above. |
| Login fails or CAPTCHA | Run again with `--show-browser` so you can see Chrome and complete CAPTCHA. |
| Empty or wrong data | Confirm `HOMESOURCE_BASE_URL` matches what you type in the browser. |
| Order rows missing serial/cost | Order may be **closed**—tool still exports what the invoice page shows. |
| “Not recognized” command | Run `pip install wdt-tools` again, or close and reopen the terminal. |

**Show the browser while logging in:**

```bash
fetch-physical-inventory --run-ids 641 --show-browser -o inventory.csv
```

---

## Words we use

| Term | Plain meaning |
|------|----------------|
| **Run ID** | Number for one physical inventory count session in HomeSource. |
| **Model number** | Product SKU / model string in the catalog. |
| **Order ID** | Sales order number. |
| **CSV** | Comma-separated spreadsheet file; opens in Excel. |
| **Tenant URL** | Your company’s HomeSource website address. |
| **`_error` column** | That row did not export cleanly—read the message in the cell. |

---

## Getting help from a developer

Share:

1. The **exact command** you ran (copy from the terminal).
2. Whether **`--show-browser`** changes anything.
3. The **first few lines** of any error message (not your password).
4. Your **run / model / order ID** (not customer PII if policy forbids it).

Developers: see [FOR_DEVELOPERS.md](FOR_DEVELOPERS.md) and [CONTRIBUTING.md](../CONTRIBUTING.md).
