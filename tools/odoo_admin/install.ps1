# Sets the tool up on this machine, safe to run again. Run through install.bat.
# ASCII only: Windows PowerShell misreads a UTF-8 script without a BOM.

$PythonPackage = "Python.Python.3.13"
$Venv = Join-Path $PSScriptRoot "venv"
$VenvPython = Join-Path $Venv "Scripts\python.exe"
$ConfigPath = Join-Path $PSScriptRoot "config.json"
$ExamplePath = Join-Path $PSScriptRoot "config.example.json"
$UsablePython = "import sys, tkinter; tkinter.Tcl(); assert sys.version_info >= (3, 10); print(sys.executable)"

# The real path of that Python if it can run the tool, otherwise nothing.
function Test-Python {
    param([string]$Command, [string[]]$Arguments = @())
    try {
        $output = & $Command @Arguments -c $UsablePython 2>$null
        if ($LASTEXITCODE -eq 0 -and $output) { return ($output | Select-Object -Last 1) }
    } catch {
        # Not there, or not runnable.
    }
}

function Find-Python {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($line in (py -0 2>$null)) {
            if ($line -match "(\d+\.\d+)") {
                $found = Test-Python "py" @("-$($Matches[1])")
                if ($found) { return $found }
            }
        }
    }
    foreach ($command in (Get-Command python -All -ErrorAction SilentlyContinue)) {
        $found = Test-Python $command.Source
        if ($found) { return $found }
    }
    # Where the installer below puts it: this session's PATH doesn't know about it yet.
    return Test-Python (Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\python.exe")
}

function Install-Python {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "winget not found. Install Python from python.org with 'tcl/tk and IDLE' ticked, then run this again."
    }
    Write-Host "Installing Python 3.13 with tcl/tk..."
    winget install --id $PythonPackage --exact --silent --scope user `
        --accept-package-agreements --accept-source-agreements `
        --override "/quiet InstallAllUsers=0 PrependPath=0 Include_tcltk=1 Include_launcher=0"
    if ($LASTEXITCODE -ne 0) { throw "winget could not install Python (code $LASTEXITCODE)." }
}

function Ensure-Venv {
    if (Test-Path $VenvPython) {
        if (Test-Python $VenvPython) {
            Write-Host "venv is ready."
            return
        }
        Write-Host "The existing venv does not work, recreating it."
    }
    $python = Find-Python
    if (-not $python) {
        Write-Host "No Python 3.10+ with tkinter found on this machine."
        Install-Python
        $python = Find-Python
        if (-not $python) { throw "Python was installed but still cannot be found. Open a new window and run this again." }
    }
    Write-Host "Using Python: $python"
    & $python -m venv --clear $Venv
    if ($LASTEXITCODE -ne 0) { throw "Could not create the venv." }
    if (-not (Test-Python $VenvPython)) { throw "The new venv cannot run tkinter." }
}

function Ensure-Config {
    if (Test-Path $ConfigPath) {
        Write-Host "Keeping the existing config.json."
        return
    }
    $config = Get-Content $ExamplePath -Raw | ConvertFrom-Json
    # This checkout is the project, whatever the example says about production's.
    $config.project_dir = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
    # Without a BOM, which the tool's JSON reading would refuse.
    [IO.File]::WriteAllText($ConfigPath, ($config | ConvertTo-Json), (New-Object Text.UTF8Encoding $false))
    Write-Host "Created config.json with project_dir = $($config.project_dir)"
    Write-Host "OPEN config.json AND CORRECT THE OTHER SETTINGS, above all database, before using the tool."
}

try {
    Ensure-Venv
    Ensure-Config
    Write-Host ""
    Write-Host "Done. Open the tool with run.bat."
} catch {
    Write-Host ""
    Write-Host "ERROR: $_"
    exit 1
}
