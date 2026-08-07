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

call :find_python
if not defined PY (
    echo.
    echo ============================================================
    echo  Unit Transfer could not start: Python was not found.
    echo ============================================================
    echo.
    echo Python is not installed, or was installed without being added to PATH.
    echo.
    echo Run Install-Dependencies.bat next to this file - it can download and
    echo install Python for you ^(your account only, no administrator needed^),
    echo put it on PATH, and add the image library this tool needs.
    echo.
    echo ^(Tip: the portable download from the Releases page needs none of this
    echo  - it bundles its own Python. This is only needed when running from source.^)
    echo.
    pause
    exit /b 9009
)

rem Pillow is the one third-party dependency (unit-card TGA<->PNG conversion).
rem Rather than failing with a cryptic import error, check for it up front and
rem try to install it automatically before the user ever sees a traceback.
%PY% -c "import PIL" >nul 2>nul
if not %errorlevel%==0 (
    echo.
    echo Pillow ^(the image library this tool needs^) is not installed yet.
    echo Installing it now with:  %PY% -m pip install pillow
    echo.
    %PY% -m pip install --disable-pip-version-check pillow
    if not %errorlevel%==0 (
        echo.
        echo ============================================================
        echo  Could not install Pillow automatically.
        echo ============================================================
        echo.
        echo This usually means there is no internet connection, or pip is
        echo missing/broken for this Python install. Try:
        echo    1. Run Install-Dependencies.bat, or
        echo    2. Open a command prompt and run:  %PY% -m pip install pillow
        echo    3. Or download the portable build from the Releases page, which
        echo       bundles Python + Pillow and needs no installation at all.
        echo.
        pause
        exit /b 9010
    )
    echo.
    echo Pillow installed successfully.
    echo.
)

%PY% app.py %*
set "RC=%errorlevel%"

rem A successful launch prints the URL and then closes this window. That happens
rem fast on a warm cache, so hold it briefly - long enough to read the address if
rem the browser didn't open on its own, short enough not to be in the way.
if "%RC%"=="0" (
    echo.
    echo  Started. This window closes in a few seconds.
    timeout /t 6 >nul 2>&1
    goto :done
)

echo.
if "%RC%"=="3" (
    echo ============================================================
    echo  Unit Transfer IS RUNNING - but no browser opened by itself.
    echo ============================================================
    echo.
    echo  Open this address in your browser:   http://127.0.0.1:8756/
    echo.
    echo  Keep this window open while you use the tool, or use the Quit
    echo  button in the tool's settings to stop it.
) else (
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
)
echo.
pause

:done
endlocal
exit /b %RC%

rem Set PY to a working interpreter command, or leave it empty. Each candidate is
rem *run*, not just located with "where": "python" on a stock Windows install is
rem usually the Microsoft Store stub, which sits on PATH but opens the Store
rem instead of running anything, and "py" can exist with no interpreter behind it.
:find_python
set "PY="
for %%c in (py python python3) do (
    if not defined PY (
        %%c -c "import sys" >nul 2>nul
        if not errorlevel 1 set "PY=%%c"
    )
)
exit /b
