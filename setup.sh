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

# ── 1. Python 3.12+ ─────────────────────────────────────
PYTHON=""
for cmd in python3.12 python3 python; do
    if command -v "$cmd" &>/dev/null; then
        ver=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || true)
        major=$("$cmd" -c "import sys; print(sys.version_info.major)" 2>/dev/null || echo 0)
        minor=$("$cmd" -c "import sys; print(sys.version_info.minor)" 2>/dev/null || echo 0)
        if [ "$major" -ge 3 ] && [ "$minor" -ge 12 ]; then
            PYTHON="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    fail "Python 3.12+ is required but not found. Install from https://python.org"
fi
info "Found $PYTHON ($ver)"

# ── 2. Virtual environment ──────────────────────────────
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment..."
    "$PYTHON" -m venv "$VENV_DIR"
    info "Virtual environment created"
else
    info "Virtual environment already exists"
fi

source "$VENV_DIR/bin/activate"

# ── 3. Python dependencies ──────────────────────────────
echo "Installing dependencies..."
pip install -q -e ".[dev]"
info "Dependencies installed"

# ── 4. Node.js + React dashboard (optional) ─────────────
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

# ── 5. Database ──────────────────────────────────────────
echo "Initialising database..."
"$PYTHON" -c "
import asyncio
from db.database import Database
async def init():
    db = Database('sqlite+aiosqlite:///./florin.db')
    await db.init()
    await db.close()
asyncio.run(init())
"
info "Database initialised (florin.db)"

# ── 6. Ollama model (optional) ──────────────────────────
if command -v ollama &>/dev/null; then
    info "Ollama found"
    read -p "Pull Ollama model (llama3.2:8b) for local LLM analysis? [y/N] " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        ollama pull llama3.2:8b
        info "Ollama model ready"
    fi
else
    warn "Ollama not installed — local LLM analysis unavailable"
    echo "    Install from https://ollama.ai if you want local LLM support."
    echo "    Cloud LLMs (Groq, Gemini, Claude CLI, OpenRouter) work without Ollama."
    echo ""
fi

# ── 7. Desktop launcher ─────────────────────────────────
LAUNCHER="Florin.command"
cat > "$LAUNCHER" << 'LAUNCHER_EOF'
#!/usr/bin/env bash
cd "$(dirname "$0")"
source .venv/bin/activate
python main.py
LAUNCHER_EOF
chmod +x "$LAUNCHER"
info "Created $LAUNCHER (double-click to launch)"

echo ""
echo "=== Setup complete! ==="
echo ""
echo "Next steps:"
echo "  1. Start the app:"
echo "     • Double-click Florin.command, or"
echo "     • Run: source .venv/bin/activate && python main.py"
echo "  2. Configure your API keys via the dashboard at http://localhost:8000/settings"
echo ""
echo "  Dashboard will be available at http://localhost:8000"
echo ""
