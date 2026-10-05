# Amadeus first-time setup
[CmdletBinding()]
param(
    [switch]$Yes,
    [switch]$NoPath,
    [switch]$SkipRuntime
)

$Root = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Definition }

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$env:AMADEUS_HOME = $Root
$env:UV_PYTHON_INSTALL_DIR = "$Root\.runtime\python"
$env:UV_CACHE_DIR = "$Root\.runtime\cache"
$env:UV_PROJECT_ENVIRONMENT = "$Root\.runtime\venv"
$env:UV_PYTHON_PREFERENCE = "only-managed"
$env:PYTHONUTF8 = "1"

Write-Host "=== Setting up Amadeus in $Root ===" -ForegroundColor Cyan

# Step 1: Download standalone uv for Windows x64
$uvExe = "$Root\.runtime\uv.exe"
if (-not (Test-Path "$Root\.runtime")) {
    New-Item -ItemType Directory -Path "$Root\.runtime" -Force | Out-Null
}

if (Test-Path $uvExe) {
    Write-Host "[1/5] Standalone uv already present at $uvExe (skipping download)." -ForegroundColor Green
} else {
    Write-Host "[1/5] Downloading standalone uv for Windows x64..." -ForegroundColor Cyan
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $prevProgress = $ProgressPreference
    $ProgressPreference = 'SilentlyContinue'
    $zipUrl = "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip"
    $tempZip = "$Root\.runtime\uv-download.zip"
    try {
        Invoke-WebRequest -Uri $zipUrl -OutFile $tempZip -UseBasicParsing
        Expand-Archive -Path $tempZip -DestinationPath "$Root\.runtime" -Force
    } catch {
        Write-Host "Error downloading or extracting uv: $_" -ForegroundColor Red
        exit 1
    } finally {
        $ProgressPreference = $prevProgress
        if (Test-Path $tempZip) {
            Remove-Item -Path $tempZip -Force -ErrorAction SilentlyContinue
        }
    }

    if (-not (Test-Path $uvExe)) {
        $found = Get-ChildItem -Path "$Root\.runtime" -Filter "uv.exe" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($found) {
            Move-Item -Path $found.FullName -Destination $uvExe -Force
        }
    }

    if (-not (Test-Path $uvExe)) {
        Write-Host "Error: uv.exe could not be found in $Root\.runtime after extraction." -ForegroundColor Red
        exit 1
    }
    Write-Host "Standalone uv installed successfully." -ForegroundColor Green
}

# Step 2: uv python install 3.12 and uv sync
Write-Host "[2/5] Setting up Python 3.12 and dependencies..." -ForegroundColor Cyan
Push-Location $Root
try {
    Write-Host "Installing Python 3.12 (folder-local)..." -ForegroundColor DarkGray
    & $uvExe python install 3.12
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Error: 'uv python install 3.12' failed with exit code $LASTEXITCODE." -ForegroundColor Red
        exit $LASTEXITCODE
    }

    Write-Host "Syncing project dependencies..." -ForegroundColor DarkGray
    if (Test-Path "$Root\uv.lock") {
        & $uvExe sync --frozen --no-dev
        if ($LASTEXITCODE -ne 0) {
            Write-Host "Warning: uv sync --frozen failed, falling back to uv sync --no-dev..." -ForegroundColor Yellow
            & $uvExe sync --no-dev
        }
    } else {
        & $uvExe sync --no-dev
    }

    if ($LASTEXITCODE -ne 0) {
        Write-Host "Error: 'uv sync' failed with exit code $LASTEXITCODE." -ForegroundColor Red
        exit $LASTEXITCODE
    }
} finally {
    Pop-Location
}
Write-Host "Python environment and dependencies synced successfully." -ForegroundColor Green

# Step 3: Create data dirs
Write-Host "[3/5] Creating data and runtime directories..." -ForegroundColor Cyan
$dataDirs = @(
    "$Root\data",
    "$Root\data\memory",
    "$Root\data\memory\notes",
    "$Root\data\sessions",
    "$Root\data\logs",
    "$Root\models",
    "$Root\bin\llama.cpp"
)
foreach ($dir in $dataDirs) {
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
}
Write-Host "Data directories verified." -ForegroundColor Green

# Step 4: Run amadeus runtime install and amadeus doctor --setup
$pythonExe = "$Root\.runtime\venv\Scripts\python.exe"
if (-not $SkipRuntime) {
    Write-Host "[4/5] Installing runtime and running doctor check..." -ForegroundColor Cyan
    if (Test-Path $pythonExe) {
        try {
            Write-Host "Running 'amadeus runtime install'..." -ForegroundColor DarkGray
            & $pythonExe -m amadeus runtime install
            if ($LASTEXITCODE -ne 0) {
                Write-Host "Hint: 'amadeus runtime install' returned exit code $LASTEXITCODE (this CLI command is being implemented by another component)." -ForegroundColor Yellow
            }
        } catch {
            Write-Host "Hint: 'amadeus runtime install' could not be executed: $_" -ForegroundColor Yellow
        }

        try {
            Write-Host "Running 'amadeus doctor --setup'..." -ForegroundColor DarkGray
            & $pythonExe -m amadeus doctor --setup
            if ($LASTEXITCODE -ne 0) {
                Write-Host "Hint: 'amadeus doctor --setup' returned exit code $LASTEXITCODE (doctor check is being implemented by another component)." -ForegroundColor Yellow
            }
        } catch {
            Write-Host "Hint: 'amadeus doctor --setup' could not be run: $_" -ForegroundColor Yellow
        }
    } else {
        Write-Host "Warning: python.exe not found at $pythonExe, skipping runtime setup." -ForegroundColor Yellow
    }
} else {
    Write-Host "[4/5] Skipping runtime installation (-SkipRuntime specified)." -ForegroundColor DarkGray
}

# Step 5: Configure PATH
Write-Host "[5/5] Configuring PATH..." -ForegroundColor Cyan
$addToPath = $false
if ($NoPath) {
    Write-Host "Skipping PATH modification (-NoPath specified)." -ForegroundColor DarkGray
} elseif ($Yes) {
    $addToPath = $true
} else {
    $response = Read-Host "Add Amadeus to your PATH so you can type ``amadeus`` anywhere? [y/N]"
    if ($response -match '^(y|yes)$') {
        $addToPath = $true
    }
}

if ($addToPath) {
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    if ($null -eq $userPath) {
        $userPath = ""
    }
    $cleanRoot = $Root.Trim().TrimEnd('\', '/')
    $alreadyIn = $false
    $pathParts = $userPath -split ';' | Where-Object { $_ -ne "" }
    foreach ($part in $pathParts) {
        $cleanPart = $part.Trim().TrimEnd('\', '/')
        if ([string]::Compare($cleanPart, $cleanRoot, [System.StringComparison]::OrdinalIgnoreCase) -eq 0) {
            $alreadyIn = $true
            break
        }
    }

    if (-not $alreadyIn) {
        $newPath = if ([string]::IsNullOrWhiteSpace($userPath)) { $Root } else { "$userPath;$Root" }
        [Environment]::SetEnvironmentVariable('Path', $newPath, 'User')
        $env:Path = "$env:Path;$Root"
        New-Item -ItemType File -Path "$Root\data\.path_added" -Force | Out-Null
        Write-Host "Added Amadeus to User PATH ($Root)." -ForegroundColor Green
    } else {
        Write-Host "Amadeus is already in your User PATH." -ForegroundColor DarkGray
        New-Item -ItemType File -Path "$Root\data\.path_added" -Force | Out-Null
    }
}

# Summary Box
Write-Host ""
Write-Host "+------------------------------------------------------------+" -ForegroundColor Green
Write-Host "|               Amadeus Setup Complete!                      |" -ForegroundColor Green
Write-Host "+------------------------------------------------------------+" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  * amadeus         : Start the interactive agent"
Write-Host "  * amadeus doctor  : Verify local LLM runtime & hardware checks"
Write-Host "  * MANUAL.md       : Read user guide and CLI reference"
Write-Host ""
if (Test-Path "$Root\data\.path_added") {
    Write-Host "PATH configured. Please restart your terminal for changes to take effect." -ForegroundColor Yellow
} else {
    Write-Host "To launch Amadeus without PATH, run: $Root\amadeus.cmd" -ForegroundColor Yellow
}
Write-Host ""
Write-Host "+------------------------------------------------------------+" -ForegroundColor Green
