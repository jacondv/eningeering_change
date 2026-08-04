@echo off
setlocal
cd /d C:\odoo-project

git fetch origin
for /f %%i in ('git rev-parse HEAD') do set LOCAL=%%i
for /f %%i in ('git rev-parse origin/main') do set REMOTE=%%i

if "%LOCAL%"=="%REMOTE%" (
    echo No updates.
    exit /b 0
)

echo Updating code...
git pull --ff-only
if errorlevel 1 exit /b 1

echo Restarting Odoo...
docker compose restart odoo

echo Update complete.