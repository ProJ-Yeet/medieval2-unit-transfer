@echo off
setlocal
title Unit Transfer - Install Dependencies

rem Run this once if Launch-Unit-Transfer.bat couldn't start the tool because
rem Python or Pillow (the image library it needs) is missing. It never closes
rem on its own, so any error stays readable.
cd /d "%~dp0"

echo ============================================================
echo  Unit Transfer - installing dependencies
echo ============================================================
echo.

where py >nul 2>nul
if %errorlevel%==0 (
    set "PY=py"
) else (
    where python >nul 2>nul
    if %errorlevel%==0 (
        set "PY=python"
    ) else (
        echo Python was not found on PATH.
        echo.
        echo Install Python 3.9+ from https://www.python.org/downloads/ and tick
        echo "Add python.exe to PATH" during setup, then run this file again.
        echo.
        echo ^(Tip: the portable download from the Releases page needs none of this
        echo  - it bundles its own Python. This is only needed when running from source.^)
        echo.
        pause
        exit /b 9009
    )
)

for /f "tokens=*" %%v in ('%PY% -c "import sys;print(sys.version)"') do echo Found Python: %%v
echo.

%PY% -c "import PIL" >nul 2>nul
if %errorlevel%==0 (
    for /f "tokens=*" %%v in ('%PY% -c "import PIL;print(PIL.__version__)"') do echo Pillow is already installed: %%v
    echo.
    echo Nothing to do - you can run Launch-Unit-Transfer.bat now.
    echo.
    pause
    exit /b 0
)

echo Pillow is not installed yet. Installing with:
echo    %PY% -m pip install pillow
echo.
%PY% -m pip install --disable-pip-version-check pillow
if not %errorlevel%==0 (
    echo.
    echo ============================================================
    echo  Install failed.
    echo ============================================================
    echo.
    echo Check your internet connection, or that pip works for this Python:
    echo    %PY% -m pip --version
    echo.
    pause
    exit /b 9010
)

echo.
echo ============================================================
echo  Done. You can run Launch-Unit-Transfer.bat now.
echo ============================================================
echo.
pause
endlocal
