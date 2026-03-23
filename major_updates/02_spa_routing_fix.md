# Phase 2: SPA Routing Fix

## Problem

When a user navigates to any non-root URL (e.g., `http://localhost:8000/research`) and reloads the page, the browser displays `{"detail":"Not Found"}`.

**Root cause:** The `StaticFiles(directory=str(static_dir), html=True)` mount in `dashboard/app.py` line 107 does NOT serve `index.html` as a catch-all SPA fallback. The `html=True` parameter only:
- Serves `{path}/index.html` when a directory is requested
- Serves `{path}.html` as a fallback for missing files

It does NOT return `index.html` for arbitrary paths like `/research` or `/research/AAPL/quantitative`.

## Fix

In `dashboard/app.py`:

1. **Remove** line 107: `app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")`

2. **Add** a catch-all route after all API routes and WebSocket registration:

```python
from fastapi.responses import FileResponse, JSONResponse

@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    """Serve React SPA — return static files if they exist, otherwise index.html."""
    # Security: prevent path traversal
    try:
        file_path = (static_dir / full_path).resolve()
        if not str(file_path).startswith(str(static_dir.resolve())):
            return FileResponse(static_dir / "index.html")
    except (ValueError, OSError):
        return FileResponse(static_dir / "index.html")

    if file_path.is_file():
        return FileResponse(file_path)

    index = static_dir / "index.html"
    if index.is_file():
        return FileResponse(index)

    return JSONResponse({"detail": "Frontend not built"}, status_code=404)
```

**Why this works:** FastAPI matches routes in registration order. API routes (all prefixed `/api/`) and WebSocket (`/ws`) are registered first and take precedence. The catch-all `/{full_path:path}` only fires for non-API paths.

## Files to Modify

- `dashboard/app.py` — remove StaticFiles mount, add catch-all route

## Testing

Add to `tests/test_dashboard.py`:

1. **API routes still work:** `GET /api/health` returns JSON with 200
2. **SPA fallback for frontend routes:** `GET /research` returns HTML (content-type `text/html`)
3. **Deeply nested SPA routes:** `GET /research/AAPL/quantitative` returns HTML
4. **Static assets served directly:** `GET /favicon.svg` returns SVG file (not index.html)
5. **WebSocket still works:** `/ws` connection succeeds
6. **Non-existent API routes return 404:** `GET /api/nonexistent` returns JSON 404

## Verification

After implementation:
1. Build frontend: `cd dashboard_ui && npm run build`
2. Start the app
3. Navigate to `http://localhost:8000/research` — should render Research page
4. Reload the page — should still show Research page (not JSON error)
5. Navigate to `http://localhost:8000/research/AAPL` — should work
6. Verify `http://localhost:8000/api/health` still returns JSON
