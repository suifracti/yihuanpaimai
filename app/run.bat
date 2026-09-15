@echo off
cd /d "%~dp0"
set NTE_DEBUG=1
if not exist "logs" mkdir logs
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd_HH-mm-ss"') do set NTE_RUN_STAMP=%%i
if not defined NTE_RUN_STAMP set NTE_RUN_STAMP=%DATE:~0,4%-%DATE:~5,2%-%DATE:~8,2%_%TIME:~0,2%-%TIME:~3,2%-%TIME:~6,2%
set NTE_RUN_STAMP=%NTE_RUN_STAMP: =0%
set NTE_LOG_FILE=%~dp0logs\run_%NTE_RUN_STAMP%.log
title NTE Auction HUD DEBUG
echo ========================================================
echo   Starting NTE Auction HUD (DEBUG)
echo   Runtime log: %NTE_LOG_FILE%
echo ========================================================
python main.py --debug
if errorlevel 1 (
    echo.
    echo Launch failed. See the traceback above.
)
echo.
echo Debug log saved to:
echo   %NTE_LOG_FILE%
pause
