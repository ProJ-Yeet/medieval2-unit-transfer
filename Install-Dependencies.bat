@echo off
setlocal enabledelayedexpansion
title Medieval 2 GUI Toolkit - Install Dependencies

rem Run this once if Launch-Medieval2-GUI-Toolkit.bat couldn't start the tool. It sorts
rem out everything the tool needs - Python itself, its PATH entry, and Pillow
rem (the image library) - asking before it downloads anything. It never closes
rem on its own, so any error stays readable.
cd /d "%~dp0"

rem Only used when Python has to be fetched from scratch. 3.12 is the sweet
rem spot: every library this tool touches ships a ready-made wheel for it, so
rem nobody ends up needing a C compiler to install Pillow.
set "PY_VER=3.12.10"
set "PY_ARCH=amd64"
if /i "%PROCESSOR_ARCHITECTURE%"=="ARM64" set "PY_ARCH=arm64"

echo ============================================================
echo  Medieval 2 GUI Toolkit - installing dependencies
echo ============================================================
echo.

call :find_python
if defined PY goto have_python

echo Python is not on PATH. Checking whether it is installed anyway...
call :find_install
if defined PYDIR goto fix_path

echo   ...no, it isn't installed.
echo.
echo ------------------------------------------------------------
echo  Python %PY_VER% can be installed for you right now:
echo    * downloaded from the official python.org site
echo    * installed for your user only, so there is no administrator
echo      prompt and nothing outside your account is touched
echo    * added to PATH, so the launcher finds it from then on
echo  About 27 MB to download. Any other Python you install later is
echo  unaffected.
echo ------------------------------------------------------------
echo.
choice /c YN /n /m "Install Python now? [Y/N] "
if errorlevel 2 goto declined
echo.
call :install_python

rem The install just happened, so this window's PATH is still the old one -
rem find the new folder on disk and put it in front for the rest of this run.
call :find_python
if defined PY goto have_python
call :find_install
if defined PYDIR goto fix_path
goto no_python

:fix_path
echo   ...found it: !PYDIR!
call :add_to_path
call :find_python
if defined PY goto have_python
goto no_python

:have_python
for /f "tokens=*" %%v in ('%PY% -c "import sys;print(sys.version)"') do echo Found Python: %%v
%PY% -c "import sys;sys.exit(0 if sys.version_info >= (3, 9) else 1)"
if errorlevel 1 (
    echo.
    echo WARNING: this tool is written for Python 3.9 or newer. Older versions
    echo may fail with syntax errors. If it does, install a current Python from
    echo https://www.python.org/downloads/ and run this file again.
)
echo.

%PY% -c "import PIL" >nul 2>nul
if %errorlevel%==0 (
    for /f "tokens=*" %%v in ('%PY% -c "import PIL;print(PIL.__version__)"') do echo Pillow is already installed: %%v
    echo.
    echo Nothing to do - you can run Launch-Medieval2-GUI-Toolkit.bat now.
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
echo  Done. You can run Launch-Medieval2-GUI-Toolkit.bat now.
echo ============================================================
echo.
pause
endlocal
exit /b 0

:declined
echo.
echo Nothing was installed.
echo.
echo Install Python 3.9+ yourself from https://www.python.org/downloads/ and
echo tick "Add python.exe to PATH" during setup, then run this file again.
echo.
echo ^(Tip: the portable download from the Releases page needs none of this
echo  - it bundles its own Python. This is only needed when running from source.^)
echo.
pause
exit /b 9009

:no_python
echo.
echo ============================================================
echo  Python still isn't usable from this window.
echo ============================================================
echo.
echo The install or the PATH change didn't take. Try, in order:
echo   1. Close this window and run this file again - a fresh window
echo      picks up a PATH that was changed while it was open.
echo   2. Install Python 3.9+ by hand from
echo      https://www.python.org/downloads/ , ticking
echo      "Add python.exe to PATH" during setup.
echo   3. Download the portable build from the Releases page, which
echo      bundles Python + Pillow and needs no installation at all.
echo.
pause
exit /b 9009


rem ------------------------------------------------------------------
rem  Subroutines
rem ------------------------------------------------------------------

rem Set PY to a working interpreter command, or leave it empty. Each candidate
rem is *run*, not just located: "python" on a stock Windows install is often the
rem Microsoft Store stub, which exists on PATH but opens the Store instead of
rem running anything, and "py" can be present with no interpreter behind it.
:find_python
set "PY="
for %%c in (py python python3) do (
    if not defined PY (
        %%c -c "import sys" >nul 2>nul
        if not errorlevel 1 set "PY=%%c"
    )
)
exit /b

rem Set PYDIR to a Python folder that exists on disk but isn't on PATH - the
rem usual result of an install where "Add python.exe to PATH" was left unticked.
rem The registry is authoritative; the folder scan catches installs that didn't
rem register (or registered under a different user).
:find_install
set "PYDIR="
for /f "tokens=2,*" %%a in ('reg query "HKCU\Software\Python\PythonCore" /s /v ExecutablePath 2^>nul') do call :use_exe "%%b"
for /f "tokens=2,*" %%a in ('reg query "HKLM\Software\Python\PythonCore" /s /v ExecutablePath 2^>nul') do call :use_exe "%%b"
if not defined PYDIR for /d %%d in ("%LocalAppData%\Programs\Python\Python3*") do if exist "%%~fd\python.exe" set "PYDIR=%%~fd"
if not defined PYDIR for /d %%d in ("%ProgramFiles%\Python3*") do if exist "%%~fd\python.exe" set "PYDIR=%%~fd"
exit /b

:use_exe
if not exist "%~1" exit /b
set "PYDIR=%~dp1"
if "!PYDIR:~-1!"=="\" set "PYDIR=!PYDIR:~0,-1!"
exit /b

rem Put PYDIR (and its Scripts folder, where pip's own commands land) on PATH:
rem permanently for the user, and immediately for this window. PowerShell does
rem the permanent half because setx silently truncates a PATH over 1024
rem characters - a well-known way to wreck someone's environment.
:add_to_path
echo Adding it to your PATH ^(your account only - no administrator needed^)...
powershell -NoProfile -Command "$d='%PYDIR%'; $cur=[Environment]::GetEnvironmentVariable('Path','User'); if(-not $cur){$cur=''}; $parts=[System.Collections.Generic.List[string]]($cur.Split(';',[StringSplitOptions]::RemoveEmptyEntries)); foreach($a in @($d,(Join-Path $d 'Scripts'))){ if($parts -notcontains $a){ $parts.Add($a) } }; [Environment]::SetEnvironmentVariable('Path',($parts -join ';'),'User')" >nul 2>nul
if errorlevel 1 echo   ^(couldn't save it permanently - using it for this run only^)
set "PATH=%PYDIR%;%PYDIR%\Scripts;%PATH%"
exit /b

rem Fetch and run the official python.org installer. Per-user, so no UAC prompt:
rem InstallAllUsers=0 keeps Python in %LocalAppData%, and InstallLauncherAllUsers=0
rem does the same for the py launcher (which otherwise installs machine-wide and
rem *would* prompt). PrependPath=1 is the "Add python.exe to PATH" tickbox.
:install_python
set "PY_URL=https://www.python.org/ftp/python/%PY_VER%/python-%PY_VER%-%PY_ARCH%.exe"
set "PY_EXE=%TEMP%\python-%PY_VER%-%PY_ARCH%.exe"
if exist "%PY_EXE%" del /q "%PY_EXE%" >nul 2>nul

echo Downloading %PY_URL%
curl -L --fail --progress-bar -o "%PY_EXE%" "%PY_URL%"
if not exist "%PY_EXE%" (
    echo   curl couldn't fetch it - trying PowerShell...
    powershell -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '%PY_URL%' -OutFile '%PY_EXE%'"
)
if not exist "%PY_EXE%" (
    echo   Download failed.
    where winget >nul 2>nul
    if not errorlevel 1 (
        echo   Falling back to winget...
        winget install --id Python.Python.3.12 -e --source winget --scope user --accept-package-agreements --accept-source-agreements
    )
    exit /b
)

echo.
echo Installing Python %PY_VER%. A progress window appears for a minute or so.
"%PY_EXE%" /passive InstallAllUsers=0 PrependPath=1 Include_launcher=1 InstallLauncherAllUsers=0 Include_pip=1 Include_test=0 AssociateFiles=0
if errorlevel 1 echo   The installer reported a problem ^(code %errorlevel%^).
del /q "%PY_EXE%" >nul 2>nul
echo.
exit /b
