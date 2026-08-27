@echo off
setlocal enabledelayedexpansion

REM Update Part Number "Created By" from an Excel PIC column.
REM Usage: update_pic.bat <db_name> <path_to_xlsx> [part_number_col_index] [pic_col_index]
REM   indices are 0-based, default 3 (PartNumber) and 13 (PIC) - matching
REM   the original test.xlsx layout. Pass different numbers if a prod
REM   file's columns are in different positions.
REM
REM Run this from the Scripts folder (docker-compose.yml's directory).

set DB=%1
set XLSX_PATH=%2
set PN_COL=%3
set PIC_COL=%4
if "%PN_COL%"=="" set PN_COL=3
if "%PIC_COL%"=="" set PIC_COL=13

if "%DB%"=="" (
    echo Usage: update_pic.bat ^<db_name^> ^<path_to_xlsx^> [part_number_col_index] [pic_col_index]
    exit /b 1
)
if "%XLSX_PATH%"=="" (
    echo Usage: update_pic.bat ^<db_name^> ^<path_to_xlsx^> [part_number_col_index] [pic_col_index]
    exit /b 1
)
if not exist "%XLSX_PATH%" (
    echo File not found: %XLSX_PATH%
    exit /b 1
)

for /f "tokens=1-4 delims=/ " %%a in ('date /t') do set TODAY=%%c%%a%%b
set TIME_NODOTS=%time::=%
set TIME_NODOTS=%TIME_NODOTS: =0%
set BACKUP_FILE=backup_before_pic_update_%DB%_%TODAY%_%TIME_NODOTS%.sql

echo === 1/5: Backing up %DB% to %BACKUP_FILE% ===
docker compose exec -T db pg_dump -U odoo %DB% > "%BACKUP_FILE%"
if errorlevel 1 (
    echo Backup FAILED - aborting.
    exit /b 1
)
echo Backup saved: %BACKUP_FILE%

echo === 2/5: Copying %XLSX_PATH% into container ===
docker compose cp "%XLSX_PATH%" odoo:/tmp/pic_update_source.xlsx
if errorlevel 1 (
    echo Copy FAILED - aborting.
    exit /b 1
)

echo === 3/5: Converting Excel to CSV ===
docker compose cp update_pic_convert.py odoo:/tmp/update_pic_convert.py
docker compose exec -T odoo python3 /tmp/update_pic_convert.py %PN_COL% %PIC_COL%
if errorlevel 1 (
    echo Conversion FAILED - aborting.
    exit /b 1
)

echo === 4/5: Dry run (no changes committed) - review carefully ===
docker compose exec -T odoo odoo shell -d %DB% --no-http < update_pic_dryrun.py

echo.
set /p CONFIRM=Dry run above looks correct? Apply for real on '%DB%'? [y/N]:
if /i not "%CONFIRM%"=="y" (
    echo Aborted - no changes made.
    exit /b 0
)

echo === 5/5: Applying update for real ===
docker compose exec -T odoo odoo shell -d %DB% --no-http < update_pic_apply.py

echo === Done. Backup kept at %BACKUP_FILE% in case you need to restore. ===
endlocal
