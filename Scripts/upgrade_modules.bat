@echo off
setlocal enabledelayedexpansion

rem Usage: upgrade_modules.bat <database> <module[,module...]>
rem Example: upgrade_modules.bat jacon_plm part_number_manager,hose_fitting_manager
rem
rem Backs up the database + filestore, proves the backup restores, upgrades
rem the given modules, checks the log for errors and restarts Odoo. Code must
rem already be at the version to deploy (git checkout/pull first) - this
rem script never touches git. On failure it stops and prints the exact
rem rollback_db.bat command for the backup it just took.
rem
rem Works from any checkout: the project folder is this script's parent
rem folder (e.g. C:\odoo-project on the server, C:\WORK\odoo-project on dev).

set "DB_NAME=%~1"
if "%DB_NAME%"=="" goto :usage

rem cmd treats commas as argument separators, so "a,b" arrives as %2 and
rem %3 - gather every remaining argument back into one comma list.
set "MODULES="
:collect_modules
shift /1
if "%~1"=="" goto :modules_collected
if defined MODULES (set "MODULES=!MODULES!,%~1") else (set "MODULES=%~1")
goto :collect_modules
:modules_collected
if "%MODULES%"=="" goto :usage

for %%I in ("%~dp0..") do set "PROJECT_DIR=%%~fI"
set "BACKUP_ROOT=C:\odoo_upgrade_backups"
set "FILESTORE=/var/lib/odoo/.local/share/Odoo/filestore"

if not exist "%PROJECT_DIR%\docker-compose.yml" (
    echo *** "%PROJECT_DIR%" has no docker-compose.yml - keep this script in the project's Scripts folder. ***
    exit /b 1
)
cd /d "%PROJECT_DIR%"

for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "TIMESTAMP=%%I"
set "BACKUP_DIR=%BACKUP_ROOT%\%DB_NAME%_%TIMESTAMP%"
set "LOG_FILE=%BACKUP_DIR%\upgrade.log"
set "VERIFY_DB=%DB_NAME%_verify_%TIMESTAMP%"

for /f "delims=" %%B in ('git rev-parse --abbrev-ref HEAD 2^>nul') do set "GIT_BRANCH=%%B"
for /f "delims=" %%C in ('git rev-parse --short HEAD 2^>nul') do set "GIT_COMMIT=%%C"

echo ============================================================
echo  Upgrade modules
echo    Project : %PROJECT_DIR%
echo    Code    : %GIT_BRANCH% @ %GIT_COMMIT%
echo    Database: %DB_NAME%
echo    Modules : %MODULES%
echo    Backup  : %BACKUP_DIR%
echo ============================================================
echo Make sure nobody is using Odoo on "%DB_NAME%" right now.
choice /C YN /M "Continue"
if errorlevel 2 exit /b 1

mkdir "%BACKUP_DIR%" || goto :fail

echo.
echo [1/6] Module versions before:
docker compose exec -T db psql -U odoo -d %DB_NAME% -c "select name, latest_version from ir_module_module where name = any(string_to_array('%MODULES%', ','))" || goto :fail

echo [2/6] Backing up database...
docker compose exec -T db pg_dump -U odoo -Fc %DB_NAME% > "%BACKUP_DIR%\%DB_NAME%.dump" || goto :fail
for %%A in ("%BACKUP_DIR%\%DB_NAME%.dump") do if %%~zA LSS 1000 (
    echo *** Database backup looks empty - does "%DB_NAME%" exist? ***
    goto :fail
)
echo       Backing up filestore...
docker compose exec -T odoo bash -c "if [ -d %FILESTORE%/%DB_NAME% ]; then tar czf - -C %FILESTORE% %DB_NAME%; fi" > "%BACKUP_DIR%\filestore.tar.gz" || goto :fail

echo [3/6] Proving the backup restores (into %VERIFY_DB%)...
docker compose exec -T db createdb -U odoo %VERIFY_DB% || goto :fail
docker compose exec -T db pg_restore -U odoo -d %VERIFY_DB% --no-owner --role=odoo < "%BACKUP_DIR%\%DB_NAME%.dump"
set "COUNT_LIVE="
set "COUNT_COPY="
set "COUNT_SQL=select (select count(*) from information_schema.tables where table_schema='public') || '/' || (select count(*) from res_partner) || '/' || (select count(*) from ir_module_module where state='installed')"
for /f "delims=" %%N in ('docker compose exec -T db psql -U odoo -d %DB_NAME% -Atc "%COUNT_SQL%"') do set "COUNT_LIVE=%%N"
for /f "delims=" %%N in ('docker compose exec -T db psql -U odoo -d %VERIFY_DB% -Atc "%COUNT_SQL%"') do set "COUNT_COPY=%%N"
docker compose exec -T db dropdb -U odoo --force %VERIFY_DB%
echo       tables/partners/installed modules - live: %COUNT_LIVE%  backup: %COUNT_COPY%
if not "%COUNT_LIVE%"=="%COUNT_COPY%" (
    echo *** Backup does not match the live database - NOT upgrading. ***
    goto :fail
)

echo [4/6] Upgrading %MODULES% (log: %LOG_FILE%)...
echo       started %time%
docker compose exec -T odoo odoo -d %DB_NAME% -u %MODULES% --stop-after-init > "%LOG_FILE%" 2>&1
echo       finished %time%

echo [5/6] Checking the log...
findstr /c:"Traceback" /c:" ERROR " /c:" CRITICAL " "%LOG_FILE%" > "%BACKUP_DIR%\errors.txt"
if not errorlevel 1 (
    echo.
    echo *** UPGRADE FAILED - first errors: ***
    powershell -NoProfile -Command "Get-Content -LiteralPath '%BACKUP_DIR%\errors.txt' -TotalCount 15"
    echo.
    echo The database rolled itself back - it is still on the old version.
    echo Put the code back to the previous version ^(git checkout ...^) and restart:
    echo     docker compose restart odoo
    goto :fail_after_upgrade
)
findstr /c:"Verify -" /c:"backed up" "%LOG_FILE%"

echo [6/6] Restarting Odoo...
docker compose restart odoo || goto :fail
echo.
echo Module versions after:
docker compose exec -T db psql -U odoo -d %DB_NAME% -c "select name, latest_version from ir_module_module where name = any(string_to_array('%MODULES%', ','))"

echo ============================================================
echo  UPGRADE DONE. Smoke test the app now.
echo  To undo it ^(database back to before the upgrade^):
echo     "%~dp0rollback_db.bat" %DB_NAME% "%BACKUP_DIR%"
echo  then put the code back ^(git checkout ...^) and restart Odoo.
echo ============================================================
exit /b 0

:fail_after_upgrade
echo Backup kept in "%BACKUP_DIR%".
exit /b 1

:fail
echo.
echo *** Stopped. Nothing was upgraded. Backup folder: "%BACKUP_DIR%" ***
exit /b 1

:usage
echo Usage: upgrade_modules.bat ^<database^> ^<module[,module...]^>
echo Example: upgrade_modules.bat jacon_plm part_number_manager,hose_fitting_manager
exit /b 1
