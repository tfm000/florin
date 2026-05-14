#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

VENV_DIR=".venv"

# ── Colors ──────────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()  { printf "${GREEN}[✓]${NC} %s\n" "$1"; }
warn()  { printf "${YELLOW}[!]${NC} %s\n" "$1"; }
fail()  { printf "${RED}[✗]${NC} %s\n" "$1"; exit 1; }

echo ""
echo "=== Florin Terminal Setup ==="
echo ""

# ── 1. Environment + dependencies ───────────────────────
# Preferred path: uv. It creates the virtual environment, provisions the
# Python interpreter pinned in .python-version, and installs the exact,
# locked dependency set from uv.lock — fully reproducible.
USE_UV=0
if command -v uv &>/dev/null; then
    USE_UV=1
    info "Found uv ($(uv --version))"

    echo "Creating virtual environment..."
    uv venv
    info "Virtual environment created (.venv)"

    echo "Installing dependencies (locked)..."
    uv sync --extra dev
    info "Dependencies installed from uv.lock"
else
    warn "uv not found — falling back to python venv + pip (NOT locked)"
    echo "    Install uv for reproducible installs:"
    echo "      curl -LsSf https://astral.sh/uv/install.sh | sh"
    echo ""

    # ── Degraded fallback: find Python 3.13+ ────────────
    PYTHON=""
    for cmd in python3.13 python3 python; do
        if command -v "$cmd" &>/dev/null; then
            major=$("$cmd" -c "import sys; print(sys.version_info.major)" 2>/dev/null || echo 0)
            minor=$("$cmd" -c "import sys; print(sys.version_info.minor)" 2>/dev/null || echo 0)
            if [ "$major" -ge 3 ] && [ "$minor" -ge 13 ]; then
                PYTHON="$cmd"
                break
            fi
        fi
    done

    if [ -z "$PYTHON" ]; then
        fail "Python 3.13+ is required but not found. Install from https://python.org or install uv."
    fi
    ver=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    info "Found $PYTHON ($ver)"

    if [ ! -d "$VENV_DIR" ]; then
        echo "Creating virtual environment..."
        "$PYTHON" -m venv "$VENV_DIR"
        info "Virtual environment created"
    else
        info "Virtual environment already exists"
    fi

    source "$VENV_DIR/bin/activate"

    echo "Installing dependencies (unlocked — install uv for reproducible builds)..."
    pip install -q -e ".[dev]"
    info "Dependencies installed"
fi

# ── 2. Node.js + React dashboard (optional) ─────────────
if command -v node &>/dev/null; then
    info "Node.js found ($(node --version))"
    if [ -d "dashboard_ui" ]; then
        echo "Building React dashboard..."
        (cd dashboard_ui && npm install --silent && npm run build --silent)
        info "Dashboard built to dashboard/static/"
    fi
else
    warn "Node.js not found — dashboard UI will not be built"
    echo "    Install with: brew install node (macOS) or apt install nodejs (Linux)"
    echo "    The REST API will still work without the frontend."
    echo ""
fi

# ── 3. Database ──────────────────────────────────────────
echo "Initialising database..."
DB_INIT_SCRIPT='
import asyncio
from db.database import Database
async def init():
    db = Database("sqlite+aiosqlite:///./florin.db")
    await db.init()
    await db.close()
asyncio.run(init())
'
if [ "$USE_UV" -eq 1 ]; then
    uv run python -c "$DB_INIT_SCRIPT"
else
    python -c "$DB_INIT_SCRIPT"
fi
info "Database initialised (florin.db)"

# ── 4. Desktop launcher ─────────────────────────────────
LAUNCHER="Florin.command"
if [ "$USE_UV" -eq 1 ]; then
    cat > "$LAUNCHER" << 'LAUNCHER_EOF'
#!/usr/bin/env bash
cd "$(dirname "$0")"
uv run python main.py
LAUNCHER_EOF
else
    cat > "$LAUNCHER" << 'LAUNCHER_EOF'
#!/usr/bin/env bash
cd "$(dirname "$0")"
source .venv/bin/activate
python main.py
LAUNCHER_EOF
fi
chmod +x "$LAUNCHER"
info "Created $LAUNCHER (double-click to launch)"

echo ""
echo "=== Setup complete! ==="
echo ""
echo "Next steps:"
echo "  1. Start the app:"
echo "     • Double-click Florin.command, or"
if [ "$USE_UV" -eq 1 ]; then
    echo "     • Run: uv run python main.py"
else
    echo "     • Run: source .venv/bin/activate && python main.py"
fi
echo "  2. Configure your API keys via the dashboard at http://localhost:8000/settings"
echo ""
echo "  Dashboard will be available at http://localhost:8000"
echo ""
