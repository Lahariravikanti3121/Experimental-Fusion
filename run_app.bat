@echo off
setlocal enabledelayedexpansion

title CrossPPI - Binding Affinity Predictor

echo.
echo  ============================================================
echo     CrossPPI - Protein-Protein Binding Affinity Predictor
echo  ============================================================
echo.

:: ---------------------------------------------------------------
:: 1. Change to the directory where this script lives
:: ---------------------------------------------------------------
cd /d "%~dp0"
echo  [1/5] Working directory: %cd%
echo.

:: ---------------------------------------------------------------
:: 2. Check that Python is available
:: ---------------------------------------------------------------
where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo  [ERROR] Python is not installed or not in your PATH.
    echo          Please install Python 3.8+ from https://www.python.org
    echo.
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo  [2/5] Found %PYVER%

:: ---------------------------------------------------------------
:: 3. Activate virtual environment (venv or conda)
:: ---------------------------------------------------------------
if exist ".venv\Scripts\activate.bat" (
    echo  [3/5] Activating virtual environment (.venv)...
    call .venv\Scripts\activate.bat
) else if exist "venv\Scripts\activate.bat" (
    echo  [3/5] Activating virtual environment (venv)...
    call venv\Scripts\activate.bat
) else if defined CONDA_DEFAULT_ENV (
    echo  [3/5] Using active Conda environment: %CONDA_DEFAULT_ENV%
) else (
    echo  [3/5] No virtual environment found. Using system Python.
)
echo.

:: ---------------------------------------------------------------
:: 4. Check that the model files exist
:: ---------------------------------------------------------------
set MODEL_COUNT=0
for %%f in (save\model_cv_*.pth) do set /a MODEL_COUNT+=1
if %MODEL_COUNT% lss 5 (
    echo  [WARNING] Expected 5 model files in save\ but found %MODEL_COUNT%.
    echo            Predictions may fail if model files are missing.
    echo.
)

:: ---------------------------------------------------------------
:: 5. Kill any existing server on port 5000
:: ---------------------------------------------------------------
for /f "tokens=5" %%p in ('netstat -aon ^| findstr ":5000 " ^| findstr "LISTENING" 2^>nul') do (
    echo  [INFO] Port 5000 is already in use (PID: %%p). Stopping it...
    taskkill /PID %%p /F >nul 2>&1
    timeout /t 2 /nobreak >nul
)

:: ---------------------------------------------------------------
:: 6. Start the Flask server in the background
:: ---------------------------------------------------------------
echo  [4/5] Starting Flask server...
echo         Loading 5 ensemble models + ESM-2 into memory.
echo         This may take 30-60 seconds on first run. Please wait...
echo.

start /b "" python app.py > server.log 2>&1

:: ---------------------------------------------------------------
:: 7. Wait for the server to be ready (poll every 2 seconds)
:: ---------------------------------------------------------------
set MAX_WAIT=60
set WAITED=0

:wait_loop
timeout /t 2 /nobreak >nul
set /a WAITED+=2

:: Try to reach the server
powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:5000/' -UseBasicParsing -TimeoutSec 2; exit 0 } catch { exit 1 }" >nul 2>&1

if %ERRORLEVEL% equ 0 (
    echo.
    echo  [5/5] Server is READY!
    echo.
    goto :server_ready
)

:: Check if the Python process died
powershell -NoProfile -Command "if (Get-Process -Name python -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }" >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo.
    echo  [ERROR] Flask server failed to start. Check the logs below:
    echo  ---------------------------------------------------------------
    if exist server.log type server.log
    echo  ---------------------------------------------------------------
    echo.
    echo  Common fixes:
    echo    - Install missing packages:  pip install -r requirements.txt
    echo    - Make sure model files exist in the save\ folder
    echo.
    pause
    exit /b 1
)

:: Show progress dots
set /a PCTG=(%WAITED%*100)/%MAX_WAIT%
<nul set /p ="  Loading... [%WAITED%s / ~%MAX_WAIT%s]   "
echo.

if %WAITED% geq %MAX_WAIT% (
    echo.
    echo  [WARNING] Server is taking longer than expected (%MAX_WAIT%s).
    echo            Opening browser anyway. Refresh the page once loaded.
    echo.
    goto :server_ready
)

goto :wait_loop

:server_ready

:: ---------------------------------------------------------------
:: 8. Open the browser
:: ---------------------------------------------------------------
echo  Opening http://127.0.0.1:5000 in your default browser...
start "" http://127.0.0.1:5000
echo.
echo  ============================================================
echo   CrossPPI is running!
echo   URL:  http://127.0.0.1:5000
echo.
echo   Press Ctrl+C to stop the server.
echo  ============================================================
echo.

:: ---------------------------------------------------------------
:: 9. Tail the server log so the user can see activity
:: ---------------------------------------------------------------
:tail_loop
if exist server.log (
    powershell -NoProfile -Command "Get-Content server.log -Wait"
)

:: If we reach here, the log file was deleted or Ctrl+C was pressed
pause
