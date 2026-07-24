@echo off
setlocal
title Unit Transfer

rem Launch the Unit Transfer tool. Runs from this file's own folder, so it works
rem no matter where the shortcut is invoked from. Any arguments (e.g. a MED2 root
rem path, or "--port 9000") are passed straight through to app.py.
cd /d "%~dp0"

rem This window ALWAYS opens, so a failed start is readable instead of a console
rem that flashes and vanishes. app.py prints its startup checks and the unit-card
rem TGA->PNG conversion progress here, then:
rem   "Show console window" OFF (default) -> it starts the server as a detached
rem      process and this window closes on its own once the server is up.
rem   "Show console window" ON  -> the server runs in this window; Ctrl+C stops it.
rem Either way, an error keeps the window open with the reason in it.

where py >nul 2>nul
if %errorlevel%==0 (
    set "PY=py"
) else (
    where python >nul 2>nul
    if %errorlevel%==0 (
        set "PY=python"
    ) else (
        echo.
        echo Unit Transfer could not start: Python was not found on PATH.
        echo.
        echo Install Python 3.9+ from https://www.python.org/downloads/ and tick
        echo "Add python.exe to PATH", then run this launcher again.
        echo.
        pause
        exit /b 9009
    )
)

%PY% app.py %*
set "RC=%errorlevel%"

if not "%RC%"=="0" (
    echo.
    echo ============================================================
    echo  Unit Transfer exited with an error ^(code %RC%^).
    echo ============================================================
    echo.
    echo  Common causes:
    echo    * Pillow is missing      -^>  pip install pillow
    echo    * Port 8756 is taken     -^>  run: Launch-Unit-Transfer.bat --port 8757
    echo    * The MED2 root moved    -^>  reset it in the UI's settings
    echo.
    echo  Full log: config\server.log
    echo  Re-run just the checks:  %PY% app.py --check
    echo.
    pause
)

endlocal
exit /b %RC%
