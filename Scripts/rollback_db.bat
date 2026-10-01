@echo off
setlocal enabledelayedexpansion

rem Usage: rollback_db.bat <database> <backup_folder>
rem Puts <database> back exactly as it was in a backup folder made by
rem upgrade_modules.bat (<database>.dump + filestore.tar.gz).
rem
rem DESTRUCTIVE: the current <database> is dropped - anything entered since
rem that backup is lost. Put the code back to the matching version too
rem (git checkout ...), otherwise Odoo runs new code on the old database.

set "DB_NAME=%~1"
set "BACKUP_DIR=%~2"
if "%DB_NAME%"=="" goto :usage
if "%BACKUP_DIR%"=="" goto :usage

for %%I in ("%~dp0..") do set "PROJECT_DIR=%%~fI"
set "FILESTORE=/var/lib/odoo/.local/share/Odoo/filestore"
set "DUMP_FILE=%BACKUP_DIR%\%DB_NAME%.dump"
set "FILESTORE_FILE=%BACKUP_DIR%\filestore.tar.gz"

if not exist "%DUMP_FILE%" (
    echo *** "%DUMP_FILE%" not found. ***
    exit /b 1
)
cd /d "%PROJECT_DIR%" || exit /b 1

echo ============================================================
echo  ROLLBACK database "%DB_NAME%"
echo  from "%BACKUP_DIR%"
echo  Everything entered in "%DB_NAME%" since that backup is LOST.
echo ============================================================
choice /C YN /M "Drop and restore %DB_NAME%"
if errorlevel 2 exit /b 1

echo [1/4] Stopping Odoo...
docker compose stop odoo || goto :fail

echo [2/4] Restoring database...
docker compose exec -T db dropdb -U odoo --if-exists --force %DB_NAME% || goto :fail
docker compose exec -T db createdb -U odoo %DB_NAME% || goto :fail
docker compose exec -T db pg_restore -U odoo -d %DB_NAME% --no-owner --role=odoo < "%DUMP_FILE%"

echo [3/4] Starting Odoo and restoring filestore...
docker compose start odoo || goto :fail
for %%A in ("%FILESTORE_FILE%") do if %%~zA GTR 0 (
    docker compose exec -T odoo bash -c "rm -rf /tmp/rb && mkdir -p /tmp/rb && tar xzf - -C /tmp/rb && rm -rf %FILESTORE%/%DB_NAME% && mv /tmp/rb/%DB_NAME% %FILESTORE%/%DB_NAME% && rm -rf /tmp/rb" < "%FILESTORE_FILE%" || goto :fail
)

echo [4/4] Restarting Odoo...
docker compose restart odoo || goto :fail
echo.
docker compose exec -T db psql -U odoo -d %DB_NAME% -c "select name, latest_version from ir_module_module where state='installed' and name in ('part_number_manager','hose_fitting_manager')"
echo ============================================================
echo  ROLLBACK DONE. Make sure the code matches this database version.
echo ============================================================
exit /b 0

:fail
echo.
echo *** Rollback stopped - see messages above. Backup is untouched in "%BACKUP_DIR%". ***
exit /b 1

:usage
echo Usage: rollback_db.bat ^<database^> ^<backup_folder^>
echo Example: rollback_db.bat jacon_plm "C:\odoo_upgrade_backups\jacon_plm_20261001_190000"
exit /b 1
