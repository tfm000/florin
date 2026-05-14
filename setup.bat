@echo off
setlocal enabledelayedexpansion

cd /d "%~dp0"

set VENV_DIR=.venv

echo.
echo === Florin Terminal Setup ===
echo.

:: ── 1. Environment + dependencies ───────────────────────
:: Preferred path: uv. It creates the virtual environment, provisions the
:: Python interpreter pinned in .python-version, and installs the exact,
:: locked dependency set from uv.lock — fully reproducible.
set USE_UV=0
where uv >nul 2>&1
if %errorlevel% equ 0 (
    set USE_UV=1
    for /f "tokens=*" %%V in ('uv --version') do echo [OK] Found %%V

    echo Creating virtual environment...
    uv venv || exit /b 1
    echo [OK] Virtual environment created (.venv)

    echo Installing dependencies (locked)...
    uv sync --extra dev || exit /b 1
    echo [OK] Dependencies installed from uv.lock
    goto :deps_done
)

echo [!] uv not found — falling back to python venv + pip (NOT locked)
echo     Install uv for reproducible installs:
echo       powershell -c "irm https://astral.sh/uv/install.ps1 ^| iex"
echo.

:: ── Degraded fallback: find Python 3.13+ ────────────────
set PYTHON=
for %%P in (python3.13 python3 python) do (
    where %%P >nul 2>&1
    if !errorlevel! equ 0 (
        for /f "tokens=*" %%V in ('%%P -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2^>nul') do set PYVER=%%V
        for /f %%M in ('%%P -c "import sys; print(sys.version_info.major)" 2^>nul') do set PYMAJOR=%%M
        for /f %%N in ('%%P -c "import sys; print(sys.version_info.minor)" 2^>nul') do set PYMINOR=%%N
        if !PYMAJOR! geq 3 if !PYMINOR! geq 13 (
            set PYTHON=%%P
            goto :found_python
        )
    )
)
echo [X] Python 3.13+ is required but not found. Install from https://python.org or install uv.
exit /b 1

:found_python
echo [OK] Found %PYTHON% (%PYVER%)

if not exist "%VENV_DIR%\Scripts\activate.bat" (
    echo Creating virtual environment...
    %PYTHON% -m venv %VENV_DIR% || exit /b 1
    echo [OK] Virtual environment created
) else (
    echo [OK] Virtual environment already exists
)

call %VENV_DIR%\Scripts\activate.bat

echo Installing dependencies (unlocked — install uv for reproducible builds)...
pip install -q -e ".[dev]" || exit /b 1
echo [OK] Dependencies installed

:deps_done

:: ── 2. Node.js + React dashboard (optional) ─────────────
where node >nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] Node.js found
    if exist "dashboard_ui" (
        echo Building React dashboard...
        cd dashboard_ui
        call npm install --silent
        call npm run build --silent
        cd ..
        echo [OK] Dashboard built
    )
) else (
    echo [!] Node.js not found — dashboard UI will not be built
    echo     Install from https://nodejs.org if you want the web dashboard.
    echo.
)

:: ── 3. Database ──────────────────────────────────────────
echo Initialising database...
set DB_INIT=import asyncio; exec('async def init():\n    from db.database import Database\n    db = Database(\"sqlite+aiosqlite:///./florin.db\")\n    await db.init()\n    await db.close()\nasyncio.run(init())')
if "%USE_UV%"=="1" (
    uv run python -c "%DB_INIT%" || exit /b 1
) else (
    python -c "%DB_INIT%" || exit /b 1
)
echo [OK] Database initialised

:: ── 4. Desktop launcher ─────────────────────────────────
if "%USE_UV%"=="1" (
    (
    echo @echo off
    echo cd /d "%%~dp0"
    echo uv run python main.py
    ) > Florin.bat
) else (
    (
    echo @echo off
    echo cd /d "%%~dp0"
    echo call .venv\Scripts\activate.bat
    echo python main.py
    ) > Florin.bat
)
echo [OK] Created Florin.bat (double-click to launch)

echo.
echo === Setup complete! ===
echo.
echo Next steps:
echo   1. Start the app:
echo      * Double-click Florin.bat, or
if "%USE_UV%"=="1" (
    echo      * Run: uv run python main.py
) else (
    echo      * Run: .venv\Scripts\activate ^&^& python main.py
)
echo   2. Configure your API keys via the dashboard at http://localhost:8000/settings
echo.
echo   Dashboard will be available at http://localhost:8000
echo.
pause
