@echo off
setlocal enabledelayedexpansion

REM Migrate Part Number's Long Description field from Html to plain Text.
REM Usage: migrate_long_description.bat <db_name>
REM
REM Steps: backup DB -> strip any HTML markup out of existing
REM long_description values (idempotent - safe to re-run) -> git pull the
REM code change (Html -> Text field) -> upgrade the module -> restart Odoo.
REM
REM This script lives in C:\scripts - the Odoo project (docker-compose.yml)
REM is elsewhere, so its path is hardcoded below rather than derived from
REM the script's own location.

set "PROJECT_DIR=C:\odoo-project"
set "SCRIPT_DIR=%~dp0"

set DB=%1
if "%DB%"=="" (
    echo Usage: migrate_long_description.bat ^<db_name^>
    exit /b 1
)

if not exist "%PROJECT_DIR%\docker-compose.yml" (
    echo.
    echo *** PROJECT_DIR "%PROJECT_DIR%" does not contain docker-compose.yml - fix the PROJECT_DIR setting at the top of this script. ***
    exit /b 1
)
cd /d "%PROJECT_DIR%"

for /f "tokens=1-4 delims=/ " %%a in ('date /t') do set TODAY=%%c%%a%%b
set TIME_NODOTS=%time::=%
set TIME_NODOTS=%TIME_NODOTS: =0%
set BACKUP_FILE=backup_before_long_description_migration_%DB%_%TODAY%_%TIME_NODOTS%.sql

echo === 1/5: Backing up %DB% to %BACKUP_FILE% ===
docker compose exec -T db pg_dump -U odoo %DB% > "%BACKUP_FILE%"
if errorlevel 1 (
    echo Backup FAILED - aborting.
    exit /b 1
)
echo Backup saved: %BACKUP_FILE%

echo.
set /p CONFIRM=About to strip HTML tags from long_description on '%DB%' and upgrade the module. Continue? [y/N]:
if /i not "%CONFIRM%"=="y" (
    echo Aborted - no changes made.
    exit /b 0
)

echo === 2/5: Stripping HTML tags from existing long_description values ===
docker compose exec -T odoo odoo shell -d %DB% --no-http < "%SCRIPT_DIR%migrate_long_description.py"
if errorlevel 1 (
    echo Strip step FAILED - aborting before touching code/module.
    exit /b 1
)

echo === 3/5: Pulling latest code (must include the Html -^> Text field change) ===
git pull
if errorlevel 1 (
    echo git pull FAILED - aborting before upgrading the module.
    exit /b 1
)

echo === 4/5: Upgrading part_number_manager module ===
docker compose exec odoo odoo -u part_number_manager -d %DB% --stop-after-init
if errorlevel 1 (
    echo Module upgrade FAILED - check the output above.
    exit /b 1
)

echo === 5/5: Restarting Odoo ===
docker compose restart odoo

echo.
echo ============================================
echo  Done. Backup kept at %BACKUP_FILE% in case you need to restore.
echo  Spot-check a few parts' Long Description on the UI.
echo ============================================
endlocal
