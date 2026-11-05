@echo off
rem Target of the Desktop shortcut. pythonw: no console window behind the tool.
if not exist "%~dp0venv\Scripts\pythonw.exe" (
    echo The tool is not installed yet. Run install.bat first.
    pause
    exit /b 1
)
start "" "%~dp0venv\Scripts\pythonw.exe" "%~dp0main.py"
