@echo off
setlocal
cd /d "%~dp0"
if not exist "dist\index.html" goto need_build
if not exist ".venv\Scripts\python.exe" (
  python -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>&1
  if errorlevel 1 goto need_python
  python -m venv .venv
  if errorlevel 1 goto failed
)
if exist ".venv\chess-requirements.lock" (
  fc /b "requirements.lock" ".venv\chess-requirements.lock" >nul 2>&1
  if not errorlevel 1 (
    fc /b "requirements.txt" ".venv\chess-requirements.txt" >nul 2>&1
    if not errorlevel 1 goto launch
  )
)
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.lock
if errorlevel 1 goto failed
copy /y requirements.lock ".venv\chess-requirements.lock" >nul
if errorlevel 1 goto failed
copy /y requirements.txt ".venv\chess-requirements.txt" >nul
if errorlevel 1 goto failed

:launch
set "CHESS_OPEN=--open"
if /i "%~1"=="--no-open" set "CHESS_OPEN="
".venv\Scripts\python.exe" -m backend.launch %CHESS_OPEN%
if errorlevel 1 goto failed
exit /b 0

:need_build
echo Build the frontend with npm ci and npm run build before starting the game.
goto failed
:need_python
echo Install Python 3.11 or later and add it to PATH, then open this file again.
:failed
pause
exit /b 1
