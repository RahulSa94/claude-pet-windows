@echo off
rem Double-click to install Claude Pet. Asks which pet you want and what to call it.
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo Claude Pet needs Python 3.10 or newer: https://www.python.org/downloads/windows/
  echo Tick "Add python.exe to PATH" while installing, then run this again.
  pause
  exit /b 1
)

echo.
echo   Claude Pet
echo   ----------
echo   1. Dog  (Rocky)
echo   2. Cat  (Snowy)
echo.
set "PET=dog"
set /p CHOICE="Which pet? [1/2, Enter = dog]: "
if "%CHOICE%"=="2" set "PET=cat"
set "NAME="
set /p NAME="Name it (Enter keeps the default): "

if defined NAME (
  python install.py install --pet %PET% --name "%NAME%" --start
) else (
  python install.py install --pet %PET% --start
)
echo.
echo Done. Restart any open Claude Code sessions so they pick up the hooks.
pause
