@echo off
setlocal enabledelayedexpansion

REM Backfill Part Number's sequence_suffix column for records that already
REM have a correct Material Group and a standard-format part_number, but
REM whose sequence_suffix was left blank (data left over from before this
REM column existed, or an import that missed it). A blank sequence_suffix
REM makes _compute_next_suffix() treat that number as "unused", so Generate
REM can hand out an already-existing part_number again (production
REM incident: 15000173 kept re-appearing as "next free" for Material Group
REM 1500 despite already existing).
REM
REM Usage: backfill_sequence_suffix.bat <db_name>
REM
REM Steps: backup DB -> backfill sequence_suffix (idempotent - safe to
REM re-run, only touches blank ones) -> git pull the _compute_next_suffix
REM fix -> upgrade the module -> restart Odoo.
REM
REM This script lives in C:\scripts - the Odoo project (docker-compose.yml)
REM is elsewhere, so its path is hardcoded below rather than derived from
REM the script's own location.

set "PROJECT_DIR=C:\odoo-project"
set "SCRIPT_DIR=%~dp0"

set DB=%1
if "%DB%"=="" (
    echo Usage: backfill_sequence_suffix.bat ^<db_name^>
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
set BACKUP_FILE=backup_before_sequence_suffix_backfill_%DB%_%TODAY%_%TIME_NODOTS%.sql

echo === 1/5: Backing up %DB% to %BACKUP_FILE% ===
docker compose exec -T db pg_dump -U odoo %DB% > "%BACKUP_FILE%"
if errorlevel 1 (
    echo Backup FAILED - aborting.
    exit /b 1
)
echo Backup saved: %BACKUP_FILE%

echo.
set /p CONFIRM=About to backfill sequence_suffix on '%DB%' and upgrade the module. Continue? [y/N]:
if /i not "%CONFIRM%"=="y" (
    echo Aborted - no changes made.
    exit /b 0
)

echo === 2/5: Backfilling blank sequence_suffix values ===
docker compose exec -T odoo odoo shell -d %DB% --no-http < "%SCRIPT_DIR%backfill_sequence_suffix.py"
if errorlevel 1 (
    echo Backfill step FAILED - aborting before touching code/module.
    exit /b 1
)

echo === 3/5: Pulling latest code (must include the _compute_next_suffix fix) ===
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
echo  Try Generate on Material Group 1500 (and any groups reported as
echo  "skipped") to confirm it no longer offers an already-used number.
echo ============================================
endlocal
