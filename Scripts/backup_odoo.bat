@echo off
setlocal enabledelayedexpansion

rem Usage: backup_odoo.bat [database_name]
rem Defaults to jacon_plm if no database name is given.
rem This script lives in C:\scripts - the Odoo project (docker-compose.yml)
rem is elsewhere, so its path is hardcoded below rather than derived from
rem the script's own location.

set "PROJECT_DIR=C:\odoo-project"
set "BACKUP_ROOT=C:\Users\JaconVNComet&JaconEq\OneDrive - MAAS Group Holdings\JACON ENGINEERING\12. App\Odoo\data_backup"
set "MONTHLY_ROOT=C:\Users\JaconVNComet&JaconEq\OneDrive - MAAS Group Holdings\JACON ENGINEERING\12. App\Odoo\data_monthly_backup"
set "KEEP_COUNT=7"
set "DB_NAME=%~1"
if "%DB_NAME%"=="" set "DB_NAME=jacon_plm"

for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "TIMESTAMP=%%I"
set "YEAR_MONTH=%TIMESTAMP:~0,6%"

set "DEST=%BACKUP_ROOT%\%DB_NAME%_%TIMESTAMP%"

echo ============================================
echo  Odoo backup: %DB_NAME%
echo  Destination: "%DEST%"
echo ============================================

if not exist "%BACKUP_ROOT%" mkdir "%BACKUP_ROOT%"
mkdir "%DEST%"

if not exist "%PROJECT_DIR%\docker-compose.yml" (
    echo.
    echo *** PROJECT_DIR "%PROJECT_DIR%" does not contain docker-compose.yml - fix the PROJECT_DIR setting at the top of this script. ***
    goto :error
)
cd /d "%PROJECT_DIR%"

echo.
echo [1/2] Backing up database "%DB_NAME%"...
docker compose exec -T db bash -c "PGPASSWORD=$POSTGRES_PASSWORD pg_dump -U odoo -Fc %DB_NAME%" > "%DEST%\%DB_NAME%.dump"
if errorlevel 1 (
    echo.
    echo *** DATABASE BACKUP FAILED - check the database name and that the containers are running. ***
    goto :error
)
for %%A in ("%DEST%\%DB_NAME%.dump") do if %%~zA LSS 1000 (
    echo.
    echo *** DATABASE BACKUP LOOKS EMPTY/INVALID - check the database name "%DB_NAME%" exists. ***
    goto :error
)

echo [2/2] Backing up filestore...
docker compose exec -T odoo tar czf - -C /var/lib/odoo/.local/share/Odoo/filestore "%DB_NAME%" > "%DEST%\filestore.tar.gz"
if errorlevel 1 (
    echo.
    echo *** FILESTORE BACKUP FAILED. ***
    goto :error
)

rem Checked every day (not just the 1st) - whichever backup happens to run
rem first in a given month is the one that gets archived, so this still
rem works if the daily task is skipped/fails on the 1st itself.
set "MONTHLY_EXISTS="
if exist "%MONTHLY_ROOT%" (
    for /f %%F in ('dir /b "%MONTHLY_ROOT%\%DB_NAME%_%YEAR_MONTH%*" 2^>nul') do set "MONTHLY_EXISTS=1"
)
if not defined MONTHLY_EXISTS (
    echo.
    echo [monthly] No backup yet for %YEAR_MONTH% - copying to monthly archive...
    if not exist "%MONTHLY_ROOT%" mkdir "%MONTHLY_ROOT%"
    xcopy "%DEST%" "%MONTHLY_ROOT%\%DB_NAME%_%TIMESTAMP%\" /E /I /Y >nul
) else (
    echo.
    echo [monthly] Backup for %YEAR_MONTH% already exists - skipping.
)

echo.
echo Pruning old backups, keeping the newest %KEEP_COUNT% for "%DB_NAME%"...
powershell -NoProfile -Command "Get-ChildItem -LiteralPath '%BACKUP_ROOT%' -Directory -Filter '%DB_NAME%_*' | Sort-Object CreationTime -Descending | Select-Object -Skip %KEEP_COUNT% | Remove-Item -Recurse -Force"

echo.
echo ============================================
echo  Backup complete: "%DEST%"
echo ============================================
goto :eof

:error
echo.
echo Backup FAILED. See messages above.
exit /b 1
