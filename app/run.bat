@echo off
cd /d "%~dp0"
set NTE_DEBUG=1
rem Single host build location. Do not add a second copy.
set "NTE_NATIVE_HOST_EXE=%~dp0..\architecture\v2\host\wgc_live_harness\bin\Release\net8.0-windows10.0.19041.0\WgcLiveHarness.exe"
set "NTE_RUN_LOG_DIR=%~dp0..\build\native-observation\runtime-logs"
if not exist "%NTE_RUN_LOG_DIR%" mkdir "%NTE_RUN_LOG_DIR%"
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd_HH-mm-ss"') do set NTE_RUN_STAMP=%%i
if not defined NTE_RUN_STAMP set NTE_RUN_STAMP=%DATE:~0,4%-%DATE:~5,2%-%DATE:~8,2%_%TIME:~0,2%-%TIME:~3,2%-%TIME:~6,2%
set NTE_RUN_STAMP=%NTE_RUN_STAMP: =0%
set "NTE_LOG_FILE=%NTE_RUN_LOG_DIR%\run_%NTE_RUN_STAMP%.log"
title NTE Auction HUD DEBUG
echo ========================================================
echo   Starting NTE Auction HUD (DEBUG)
echo   Runtime log: %NTE_LOG_FILE%
echo ========================================================
if not defined NTE_PYTHON_EXE if exist "%~dp0..\.venv\Scripts\python.exe" set "NTE_PYTHON_EXE=%~dp0..\.venv\Scripts\python.exe"
if not defined NTE_PYTHON_EXE if exist "%~dp0..\build\takeover_20260905\repro-venv\Scripts\python.exe" set "NTE_PYTHON_EXE=%~dp0..\build\takeover_20260905\repro-venv\Scripts\python.exe"
if not defined NTE_PYTHON_EXE set "NTE_PYTHON_EXE=python"
echo   Python runtime: %NTE_PYTHON_EXE%
"%NTE_PYTHON_EXE%" main.py --debug
if errorlevel 1 (
    echo.
    echo Launch failed. See the traceback above.
)
echo.
echo Debug log saved to:
echo   %NTE_LOG_FILE%
pause
