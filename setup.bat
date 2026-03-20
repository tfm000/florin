@echo off
setlocal enabledelayedexpansion

cd /d "%~dp0"

set VENV_DIR=.venv

echo.
echo === Penny Stock Sentinel Setup ===
echo.

:: ── 1. Python 3.12+ ─────────────────────────────────────
set PYTHON=
for %%P in (python3 python) do (
    where %%P >nul 2>&1
    if !errorlevel! equ 0 (
        for /f "tokens=*" %%V in ('%%P -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2^>nul') do set PYVER=%%V
        for /f %%M in ('%%P -c "import sys; print(sys.version_info.major)" 2^>nul') do set PYMAJOR=%%M
        for /f %%N in ('%%P -c "import sys; print(sys.version_info.minor)" 2^>nul') do set PYMINOR=%%N
        if !PYMAJOR! geq 3 if !PYMINOR! geq 12 (
            set PYTHON=%%P
            goto :found_python
        )
    )
)
echo [X] Python 3.12+ is required but not found. Install from https://python.org
exit /b 1

:found_python
echo [OK] Found %PYTHON% (%PYVER%)

:: ── 2. Virtual environment ──────────────────────────────
if not exist "%VENV_DIR%\Scripts\activate.bat" (
    echo Creating virtual environment...
    %PYTHON% -m venv %VENV_DIR%
    echo [OK] Virtual environment created
) else (
    echo [OK] Virtual environment already exists
)

call %VENV_DIR%\Scripts\activate.bat

:: ── 3. Python dependencies ──────────────────────────────
echo Installing dependencies...
pip install -q -e ".[dev]"
echo [OK] Dependencies installed

:: ── 4. Node.js + React dashboard (optional) ─────────────
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

:: ── 5. Environment config ───────────────────────────────
if not exist ".env" (
    copy .env.example .env >nul
    echo [OK] .env created from .env.example — edit it with your API keys
) else (
    echo [OK] .env already exists
)

:: ── 6. Database ─────────────────────────────────────────
echo Initialising database...
%PYTHON% -c "import asyncio; from db.database import Database; asyncio.run((lambda: (db := Database('sqlite+aiosqlite:///./sentinel.db')) or asyncio.ensure_future(db.init()))())" 2>nul
%PYTHON% -c "import asyncio; exec('async def init():\n    from db.database import Database\n    db = Database(\"sqlite+aiosqlite:///./sentinel.db\")\n    await db.init()\n    await db.close()\nasyncio.run(init())')"
echo [OK] Database initialised

:: ── 7. Desktop launcher ─────────────────────────────────
(
echo @echo off
echo cd /d "%%~dp0"
echo call .venv\Scripts\activate.bat
echo python main.py
) > Sentinel.bat
echo [OK] Created Sentinel.bat (double-click to launch)

echo.
echo === Setup complete! ===
echo.
echo Next steps:
echo   1. Edit .env with your API keys (see README.md for details)
echo   2. Start the app:
echo      * Double-click Sentinel.bat, or
echo      * Run: .venv\Scripts\activate ^&^& python main.py
echo.
echo   Dashboard will be available at http://localhost:8000
echo.
pause
