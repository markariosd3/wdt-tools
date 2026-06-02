# Publishing to PyPI (global install)

**WDT Tools** is published on PyPI as **`wdt-tools`** (Warehouse Duct Tape —
unofficial HomeSource tenant export CLIs).

This project is packaged so anyone can install it with **pip** from the
[Python Package Index (PyPI)](https://pypi.org/) — the main registry Python
tools search (pip, uv, poetry, etc.).

> **Note:** [PyPI](https://pypi.org/) (package index) is different from
> [PyPy](https://www.pypy.org/) (an alternate Python runtime). This project
> targets CPython 3.10+; wheels built here work with standard `pip install`.

After publishing, users can run:

```bash
pip install wdt-tools
fetch-physical-inventory --help
```

---

## One-time setup (maintainer)

### 1. Create accounts

| Service | URL | Purpose |
|---------|-----|---------|
| **PyPI** | https://pypi.org/account/register/ | Production packages |
| **TestPyPI** | https://test.pypi.org/account/register/ | Dry-run uploads (optional) |

Use **two-factor authentication** on PyPI.

### 2. Reserve the package name

Check the name is free:

```bash
pip index versions wdt-tools
# or visit https://pypi.org/project/wdt-tools/
```

If `wdt-tools` is taken, change `name` in `pyproject.toml` (e.g.
`homesource-export`) and update README install instructions.

### 3. Configure GitHub → PyPI (recommended)

Use **[PyPI trusted publishing](https://docs.pypi.org/trusted-publishers/)**
so you never store a long-lived API token in GitHub:

1. Build the package locally once (see below) so you know it works.
2. On PyPI: **Your projects** → **Add new project** → name `wdt-tools`
   (or create it on first upload).
3. PyPI → project → **Publishing** → **Add a new publisher**:
   - Owner: your GitHub user or org
   - Repository: `wdt-tools`
   - Workflow: `publish.yml`
   - Environment: `pypi` (optional but recommended)

4. GitHub repo → **Settings** → **Environments** → create `pypi` with
   protection rules if you want approval before release.

### 4. Update metadata before the first release

In `pyproject.toml`, set real values for:

- `[project.authors]`
- `[project.urls]` (replace `YOUR_USERNAME`)

Commit `LICENSE` (already MIT) and ensure README has no broken links.

---

## Release workflow (each version)

### 1. Bump version

Edit **`VERSION`** (single source of truth) and **`CHANGELOG.md`**, then commit.

`pyproject.toml` reads version from `VERSION` at build time.

### 2. Tag in git

```bash
git tag -a v1.0.0 -m "Release 1.0.0"
git push origin v1.0.0
```

### 3. Publish

**Option A — GitHub Release (automated)**

1. GitHub → **Releases** → **Draft a new release**
2. Choose tag `v1.0.0`
3. Publish release → triggers `.github/workflows/publish.yml` (if trusted
   publishing is configured)

**Option B — Manual upload**

```bash
python -m pip install --upgrade build twine
python -m build
twine check dist/*

# TestPyPI first (optional)
twine upload --repository testpypi dist/*

# Production PyPI (API token or `twine login`)
twine upload dist/*
```

Create a PyPI API token at https://pypi.org/manage/account/token/ scoped to
this project if not using trusted publishing.

---

## Verify after publish

```bash
pip install wdt-tools
fetch-physical-inventory --version
fetch-model -h
```

Search https://pypi.org/search/?q=homesource — your project should appear
within minutes.

---

## How people discover the package

| Channel | What helps |
|---------|------------|
| **PyPI** | `name`, `description`, `keywords`, `classifiers`, README |
| **GitHub** | Public repo, topics (`homesource`, `cli`, `export`), link in README |
| **README** | `pip install wdt-tools` at the top |
| **Google** | PyPI page + GitHub rank for "homesource python export" over time |

PyPI does not promote new projects automatically; a clear README, semver tags,
and links between GitHub and PyPI help search engines and `pip search` mirrors.

---

## Console commands installed by pip

| Command | Same as |
|---------|---------|
| `fetch-physical-inventory` | `python fetch_physical_inventory.py` |
| `fetch-model` | `python fetch_model.py` |
| `fetch-order-detail` | `python fetch_order_detail.py` |
| `fetch-physical-inventory-with-model` | `python fetch_physical_inventory_with_model.py` |

Scripts still work when cloned from git (`python fetch_*.py`).
