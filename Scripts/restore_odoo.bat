@echo off
setlocal enabledelayedexpansion

rem Usage: restore_odoo.bat <backup_folder> <target_database_name>
rem Example: restore_odoo.bat C:\odoo_backup\jacon_plm_20260804_125445 jacon_plm_restore
rem
rem DESTRUCTIVE: if <target_database_name> already exists it is DROPPED
rem and recreated from the backup. Restoring into a name that does not
rem yet exist (e.g. a "_restore" or "_test" copy) is the safe way to
rem verify a backup without touching a live database.
rem
rem This script lives in C:\scripts - the Odoo project (docker-compose.yml)
rem is elsewhere, so its path is hardcoded below rather than derived from
rem the script's own location.

set "PROJECT_DIR=C:\odoo-project"

set "BACKUP_DIR=%~1"
set "DB_NAME=%~2"

if "%BACKUP_DIR%"=="" (
    echo Usage: restore_odoo.bat ^<backup_folder^> ^<target_database_name^>
    exit /b 1
)
if "%DB_NAME%"=="" (
    echo Usage: restore_odoo.bat ^<backup_folder^> ^<target_database_name^>
    exit /b 1
)
if not exist "%BACKUP_DIR%" (
    echo *** Backup folder not found: "%BACKUP_DIR%" ***
    exit /b 1
)

rem Locate the .dump file and derive the original database name from it
set "DUMP_FILE="
set "SRC_DB="
for %%F in ("%BACKUP_DIR%\*.dump") do (
    set "DUMP_FILE=%%F"
    set "SRC_DB=%%~nF"
)
if "%DUMP_FILE%"=="" (
    echo *** No .dump file found in "%BACKUP_DIR%" ***
    exit /b 1
)
set "FILESTORE_FILE=%BACKUP_DIR%\filestore.tar.gz"
if not exist "%FILESTORE_FILE%" (
    echo *** filestore.tar.gz not found in "%BACKUP_DIR%" ***
    exit /b 1
)

echo ============================================
echo  Restore backup: "%BACKUP_DIR%"
echo  Source database (in backup): %SRC_DB%
echo  Target database:             %DB_NAME%
echo ============================================
echo.
echo WARNING: if database "%DB_NAME%" already exists, it will be DROPPED.
choice /C YN /M "Continue"
if errorlevel 2 exit /b 1

if not exist "%PROJECT_DIR%\docker-compose.yml" (
    echo.
    echo *** PROJECT_DIR "%PROJECT_DIR%" does not contain docker-compose.yml - fix the PROJECT_DIR setting at the top of this script. ***
    exit /b 1
)
cd /d "%PROJECT_DIR%"

echo.
echo [1/3] Dropping and recreating database "%DB_NAME%"...
docker compose exec -T db bash -c "PGPASSWORD=$POSTGRES_PASSWORD dropdb -U odoo --if-exists %DB_NAME% && PGPASSWORD=$POSTGRES_PASSWORD createdb -U odoo %DB_NAME%"
if errorlevel 1 (
    echo *** Failed to drop/create database. ***
    goto :error
)

echo [2/3] Restoring database dump...
docker compose exec -T db bash -c "PGPASSWORD=$POSTGRES_PASSWORD pg_restore -U odoo -d %DB_NAME% --no-owner --role=odoo" < "%DUMP_FILE%"
if errorlevel 1 (
    echo.
    echo *** pg_restore reported errors - check the output above.
    echo *** Some warnings (e.g. missing extensions/roles^) are often harmless, review before trusting this restore. ***
)

echo [3/3] Restoring filestore...
rem Extract into a throwaway staging folder first - never touch a
rem live filestore folder that happens to share the backup's original
rem database name (e.g. restoring a "jacon_plm" backup into
rem "jacon_plm_test" must not delete/overwrite the real "jacon_plm").
docker compose exec -T odoo bash -c "STAGE=/tmp/restore_staging_$$; rm -rf $STAGE; mkdir -p $STAGE; tar xzf - -C $STAGE && rm -rf /var/lib/odoo/.local/share/Odoo/filestore/%DB_NAME% && mv $STAGE/%SRC_DB% /var/lib/odoo/.local/share/Odoo/filestore/%DB_NAME% && rm -rf $STAGE" < "%FILESTORE_FILE%"
if errorlevel 1 (
    echo *** Filestore restore failed. ***
    goto :error
)

echo.
echo ============================================
echo  Restore complete: database "%DB_NAME%" is ready.
echo  Restart Odoo if it was already running against this database:
echo    docker compose restart odoo
echo ============================================
goto :eof

:error
echo.
echo Restore FAILED. See messages above.
exit /b 1
