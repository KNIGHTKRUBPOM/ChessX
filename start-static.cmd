@echo off
setlocal
cd /d "%~dp0"
where npm.cmd >nul 2>&1
if errorlevel 1 goto need_node

set "CHESS_NODE_DIR="
for /f "delims=" %%N in ('where.exe node.exe 2^>nul') do (
  if not defined CHESS_NODE_DIR (
    "%%N" -e "const [major,minor]=process.versions.node.split('.').map(Number); process.exit(process.release.lts && ((major===22 && minor>=12) || major===24 || major===26) ? 0 : 1)" >nul 2>&1
    if not errorlevel 1 set "CHESS_NODE_DIR=%%~dpN"
  )
)
if not defined CHESS_NODE_DIR goto need_node
set "PATH=%CHESS_NODE_DIR%;%PATH%"

if not exist "node_modules\.bin\vite.cmd" (
  call npm.cmd ci --no-audit --no-fund
  if errorlevel 1 goto failed
)
call npm.cmd run dev -- --open
if errorlevel 1 goto failed
exit /b 0

:need_node
echo Install Node.js 24 LTS with npm, then open this file again.
:failed
pause
exit /b 1
