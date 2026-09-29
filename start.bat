@echo off
rem One-click start for Windows: sets up everything on first run, then opens the app.
setlocal
cd /d "%~dp0"
if "%PORT%"=="" set PORT=8000

where py >nul 2>nul && (set PY=py -3) || (set PY=python)

if not exist ".venv\Scripts\python.exe" (
    echo [WebPilot] First run: creating the Python environment...
    %PY% -m venv .venv || goto :nopython
    echo [WebPilot] Installing dependencies ^(1-2 minutes^)...
    ".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
    ".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt || goto :fail
)
if not exist ".env" copy ".env.example" ".env" >nul

rem Browser: Playwright's Chromium, or Microsoft Edge (always present on Windows) if the download fails.
findstr /b /c:"BROWSER_CHANNEL=msedge" ".env" >nul 2>nul
if errorlevel 1 (
    if not exist ".venv\.chromium-ok" (
        echo [WebPilot] Installing the Chromium browser...
        ".venv\Scripts\python.exe" -m playwright install chromium >nul 2>nul && (echo ok> ".venv\.chromium-ok") || (
            echo [WebPilot] Chromium download failed, using Microsoft Edge instead.
            echo BROWSER_CHANNEL=msedge>> ".env"
        )
    )
)

echo.
echo [WebPilot] Starting on http://localhost:%PORT%
echo [WebPilot] Optional: paste a free Gemini key in .env (GEMINI_API_KEY=...) to give it any task on any site.
echo [WebPilot] Close this window to stop.
echo.
if "%NO_BROWSER%"=="" start "" /b cmd /c "timeout /t 4 >nul & start http://localhost:%PORT%"
".venv\Scripts\python.exe" -m uvicorn app.main:app --port %PORT%
goto :eof

:nopython
echo [WebPilot] Python 3.12+ was not found. Install it from https://www.python.org/downloads/ and run this again.
pause
exit /b 1

:fail
echo [WebPilot] Installing dependencies failed. See the messages above.
pause
exit /b 1
