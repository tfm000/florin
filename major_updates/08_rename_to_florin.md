# Phase 8: Rename to Florin

## Changes

Replace all "Sentinel" and "penny-stock" references throughout the codebase. Update logos and branding.

## Key Renames

| Old | New | Location |
|-----|-----|----------|
| `SentinelError` | `FlorinError` | `core/exceptions.py` + all imports |
| `SentinelBot` | `FlorinBot` | `telegram_bot/bot.py` + imports |
| `class Sentinel` | `class Florin` | `main.py` |
| `sentinel_exception_handler` | `florin_exception_handler` | `dashboard/middleware.py` |
| `"Sentinel Terminal"` | `"Florin Terminal"` | `dashboard/app.py`, `App.jsx`, `index.html` |
| `penny-stock-sentinel` | `florin` | `pyproject.toml` name |
| `sentinel = "main:cli_entry"` | `florin = "main:cli_entry"` | `pyproject.toml` scripts |
| `sentinel.db` | `florin.db` | `config/settings.py` default |
| `sentinel` service | `florin` | `docker-compose.yml` |

## Logo Implementation

1. Copy `florin_light.PNG` → `dashboard_ui/public/florin_light.png`
2. Copy `florin_dark.PNG` → `dashboard_ui/public/florin_dark.png`
3. Update `dashboard_ui/index.html`:
   ```html
   <link rel="icon" type="image/png" href="/florin_light.png">
   <title>Florin Terminal</title>
   ```
4. In `App.jsx`, add logo in the navbar:
   ```jsx
   <img
     src="/florin_light.png"
     alt="Florin"
     className="h-8 w-auto"
   />
   ```
   For dark/light mode switching (if implemented later):
   ```jsx
   <picture>
     <source srcSet="/florin_dark.png" media="(prefers-color-scheme: dark)" />
     <img src="/florin_light.png" alt="Florin" className="h-8 w-auto" />
   </picture>
   ```
   Note: Since the app is currently dark-theme only, use `florin_dark.png` as the in-app logo and `florin_light.png` as the favicon (which appears on browser tab with light background).
5. Delete `dashboard_ui/public/favicon.svg`

## Approach

### Step 1: Search for all references

```bash
grep -rni "sentinel" --include="*.py" --include="*.jsx" --include="*.js" --include="*.json" --include="*.toml" --include="*.yml" --include="*.yaml" --include="*.md" --include="*.html" --include="*.sh" --include="*.bat" --include="*.ini" .
grep -rni "penny.stock\|penny_stock\|PennyStock" --include="*.py" --include="*.jsx" --include="*.js" --include="*.json" --include="*.toml" --include="*.md" .
```

### Step 2: Rename in order (to avoid broken imports)

1. `core/exceptions.py` — `SentinelError` → `FlorinError`
2. All files importing `SentinelError` — update imports
3. `dashboard/middleware.py` — handler rename
4. `telegram_bot/bot.py` — `SentinelBot` → `FlorinBot`
5. `main.py` — `class Sentinel` → `class Florin`, update all references
6. `dashboard/app.py` — title, error handler reference
7. Frontend files — title, text, confirm dialogs
8. Config files — pyproject.toml, package.json, Docker, alembic.ini
9. Documentation — README.md, agent.md, CLAUDE_CODE_BRIEFING.md
10. Tests — update all references
11. All remaining "penny stock" references → generic terms ("asset", "stock")

### Step 3: Database backward compatibility

In `config/settings.py`, change default:
```python
database_url: str = "sqlite+aiosqlite:///./florin.db"
```

Add a check in `db/database.py` or `main.py`:
```python
# If florin.db doesn't exist but sentinel.db does, use sentinel.db
import os
if not os.path.exists("florin.db") and os.path.exists("sentinel.db"):
    logger.info("Migrating from sentinel.db to florin.db")
    os.rename("sentinel.db", "florin.db")
```

### Step 4: Verification

```bash
# After all renames:
grep -rni "sentinel" --include="*.py" --include="*.jsx" --include="*.js" --include="*.json" --include="*.toml" --include="*.yml" --include="*.md" --include="*.html" .
# Should return 0 matches (except possibly in git history references or this plan file)

grep -rni "penny.stock\|penny_stock" --include="*.py" --include="*.jsx" --include="*.js" .
# Should return 0 matches
```

## Files to Modify

~50 files — every Python, frontend, config, doc, and test file that contains "sentinel", "Sentinel", "penny stock", or "penny_stock".

Key files:
- `core/exceptions.py`
- `dashboard/middleware.py`
- `dashboard/app.py`
- `dashboard/schemas.py`
- `telegram_bot/bot.py`
- `telegram_bot/handlers/commands.py`
- `main.py`
- `config/settings.py`
- `db/database.py`
- `dashboard_ui/src/App.jsx`
- `dashboard_ui/index.html`
- `pyproject.toml`
- `dashboard_ui/package.json`
- `Dockerfile`
- `docker-compose.yml`
- `README.md`
- `agent.md`
- `alembic.ini`
- `setup.sh` / `setup.bat`
- All test files with references

## Testing

- Run full test suite — all tests must pass with new names
- Verify CLI entry point `florin` works after `pip install -e .`
- Verify Docker build succeeds
- Grep for remaining "sentinel" or "penny-stock" references (should be 0)
- Verify favicon displays correctly in browser
- Verify logo displays in app navbar
