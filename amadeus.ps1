# Amadeus launcher
$Root = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Definition }

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$env:AMADEUS_HOME = $Root
$env:UV_PYTHON_INSTALL_DIR = "$Root\.runtime\python"
$env:UV_CACHE_DIR = "$Root\.runtime\cache"
$env:UV_PROJECT_ENVIRONMENT = "$Root\.runtime\venv"
$env:UV_PYTHON_PREFERENCE = "only-managed"
$env:PYTHONUTF8 = "1"

$subCommand = if ($args.Count -gt 0) { $args[0] } else { $null }

if ($subCommand -eq 'setup') {
    $scriptArgs = if ($args.Count -gt 1) { $args[1..($args.Count - 1)] } else { @() }
    & "$Root\setup.ps1" @scriptArgs
    exit $LASTEXITCODE
}

if ($subCommand -eq 'uninstall') {
    $scriptArgs = if ($args.Count -gt 1) { $args[1..($args.Count - 1)] } else { @() }
    & "$Root\uninstall.ps1" @scriptArgs
    exit $LASTEXITCODE
}

if ($subCommand -eq 'repair') {
    $uvExe = "$Root\.runtime\uv.exe"
    if (-not (Test-Path $uvExe)) {
        Write-Host "Amadeus standalone uv not found at $uvExe." -ForegroundColor Yellow
        Write-Host "Please run setup.ps1 first: .\setup.ps1" -ForegroundColor Yellow
        exit 1
    }

    Write-Host "Repairing Amadeus virtual environment..." -ForegroundColor Cyan
    Push-Location $Root
    try {
        if (Test-Path "$Root\uv.lock") {
            & $uvExe sync --frozen --no-dev --reinstall
        } else {
            & $uvExe sync --no-dev --reinstall
        }
        $code = $LASTEXITCODE
    } finally {
        Pop-Location
    }

    if ($null -eq $code) {
        $code = 0
    }

    if ($code -eq 0) {
        Write-Host "Amadeus environment repaired successfully." -ForegroundColor Green
    } else {
        Write-Host "Amadeus repair failed with exit code $code." -ForegroundColor Red
    }
    exit $code
}

# Everything else: run python.exe -m amadeus @args preserving current working directory
$pythonExe = "$Root\.runtime\venv\Scripts\python.exe"

if (-not (Test-Path $pythonExe)) {
    Write-Host "Amadeus environment is broken - if you moved the folder, run: amadeus repair" -ForegroundColor Yellow
    exit 1
}

$code = 0
try {
    & $pythonExe -m amadeus @args
    $code = $LASTEXITCODE
    if ($null -eq $code) {
        $code = 0
    }
} catch {
    Write-Host "Amadeus environment is broken - if you moved the folder, run: amadeus repair" -ForegroundColor Yellow
    exit 1
}

if ($code -ne 0) {
    $isBroken = $false
    # Windows loader failure exit codes (e.g. 103, 9009, 0xC0000135, etc.)
    if ($code -in @(103, 9009, -1073741515, -1073741511, -1073741701, 3221225781)) {
        $isBroken = $true
    } else {
        $pyvenvCfg = "$Root\.runtime\venv\pyvenv.cfg"
        if (Test-Path $pyvenvCfg) {
            $homeLine = Get-Content $pyvenvCfg -ErrorAction SilentlyContinue | Where-Object { $_ -match '^\s*home\s*=' } | Select-Object -First 1
            if ($homeLine) {
                $homePath = ($homeLine -split '=', 2)[1].Trim()
                if (-not (Test-Path $homePath)) {
                    $isBroken = $true
                }
            } else {
                $isBroken = $true
            }
        } else {
            $isBroken = $true
        }
    }

    if ($isBroken) {
        Write-Host "Amadeus environment is broken - if you moved the folder, run: amadeus repair" -ForegroundColor Yellow
    }
}

exit $code
