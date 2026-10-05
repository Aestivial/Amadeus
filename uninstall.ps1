# Amadeus uninstaller
[CmdletBinding()]
param(
    [switch]$Force,
    [switch]$KeepModels,
    [switch]$WhatIf,
    [switch]$DryRun
)

$isDryRun = ($WhatIf.IsPresent -or $DryRun.IsPresent)
$Root = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Definition }

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host "Inspecting Amadeus installation at $Root..." -ForegroundColor Cyan

# Calculate total size quickly
$sizeBytes = 0
try {
    $measure = Get-ChildItem -LiteralPath $Root -Recurse -File -Force -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum
    if ($measure -and $measure.Sum) {
        $sizeBytes = $measure.Sum
    }
} catch {
    $sizeBytes = 0
}

$sizeMB = [math]::Round($sizeBytes / 1MB, 2)
$sizeGB = [math]::Round($sizeBytes / 1GB, 2)
$sizeFormatted = if ($sizeGB -ge 1.0) { "$sizeGB GB ($sizeBytes bytes)" } else { "$sizeMB MB ($sizeBytes bytes)" }

# Check User PATH entry
$currentUserPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if ($null -eq $currentUserPath) {
    $currentUserPath = ""
}
$hasPathEntry = $false
$cleanRoot = $Root.Trim().TrimEnd('\', '/')
$pathParts = $currentUserPath -split ';' | Where-Object { $_ -ne "" }
foreach ($part in $pathParts) {
    $cleanPart = $part.Trim().TrimEnd('\', '/')
    if ([string]::Compare($cleanPart, $cleanRoot, [System.StringComparison]::OrdinalIgnoreCase) -eq 0) {
        $hasPathEntry = $true
        break
    }
}

# Display summary
Write-Host ""
Write-Host "================== Amadeus Uninstaller ==================" -ForegroundColor Yellow
Write-Host "Target Folder:   $Root"
Write-Host "Folder Size:     $sizeFormatted"
Write-Host "User PATH entry: $(if ($hasPathEntry) { 'Present (will be removed)' } else { 'Not present' })"
if ($KeepModels) {
    $backupDir = Join-Path (Split-Path -Parent $Root) 'Amadeus-models-backup'
    Write-Host "Models Folder:   Will be moved to -> $backupDir" -ForegroundColor Green
} else {
    Write-Host "Models Folder:   Will be PERMANENTLY DELETED (use -KeepModels to preserve)" -ForegroundColor Red
}
Write-Host "=========================================================" -ForegroundColor Yellow
Write-Host ""

# Ask for confirmation
if (-not $Force -and -not $isDryRun) {
    Write-Host "WARNING: This will permanently delete Amadeus and all contained data." -ForegroundColor Red
    $answer = Read-Host "Type 'yes' to proceed with uninstall"
    if ($answer -ne 'yes') {
        Write-Host "Uninstall cancelled by user." -ForegroundColor DarkGray
        exit 0
    }
}

# Preserve models if requested
if ($KeepModels) {
    $modelsDir = "$Root\models"
    if (Test-Path $modelsDir) {
        $backupDir = Join-Path (Split-Path -Parent $Root) 'Amadeus-models-backup'
        if ($isDryRun) {
            Write-Host "[DryRun] Would move '$modelsDir' to '$backupDir'" -ForegroundColor Cyan
        } else {
            Write-Host "Preserving models: moving '$modelsDir' to '$backupDir'..." -ForegroundColor Cyan
            if (-not (Test-Path $backupDir)) {
                New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
            }
            Move-Item -Path "$modelsDir\*" -Destination $backupDir -Force -ErrorAction SilentlyContinue
            Remove-Item -Path $modelsDir -Recurse -Force -ErrorAction SilentlyContinue
            Write-Host "Models preserved at: $backupDir" -ForegroundColor Green
        }
    }
}

# Stop any llama-server.exe or running processes inside this folder
Write-Host "Checking for running processes inside Amadeus folder..." -ForegroundColor Cyan
$runningProcesses = Get-Process -ErrorAction SilentlyContinue | Where-Object {
    try {
        if ($_.Path -and ($_.Path -like "$Root*")) {
            return $true
        }
    } catch {}
    return $false
}

foreach ($proc in $runningProcesses) {
    if ($isDryRun) {
        Write-Host "[DryRun] Would stop process $($proc.Name) (PID $($proc.Id))" -ForegroundColor Yellow
    } else {
        Write-Host "Stopping process $($proc.Name) (PID $($proc.Id))..." -ForegroundColor Yellow
        try {
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        } catch {}
    }
}

# Remove the folder's PATH entry from HKCU Path
if ($hasPathEntry) {
    if ($isDryRun) {
        Write-Host "[DryRun] Would remove $Root from User PATH" -ForegroundColor Cyan
    } else {
        Write-Host "Removing $Root from User PATH..." -ForegroundColor Cyan
        $remaining = $pathParts | Where-Object {
            $p = $_.Trim().TrimEnd('\', '/')
            [string]::Compare($p, $cleanRoot, [System.StringComparison]::OrdinalIgnoreCase) -ne 0
        }
        $newPath = ($remaining -join ';')
        [Environment]::SetEnvironmentVariable('Path', $newPath, 'User')
        Write-Host "Removed Amadeus from User PATH." -ForegroundColor Green
    }
}

# Final instructions and detached deletion
Write-Host ""
Write-Host "Amadeus folder deletion scheduled." -ForegroundColor Yellow
Write-Host "IMPORTANT: Please close any terminals, command prompts, or file explorers" -ForegroundColor Yellow
Write-Host "           currently opened inside: $Root" -ForegroundColor Yellow
Write-Host ""

if ($isDryRun) {
    Write-Host "[DryRun] Would execute detached deletion: cmd.exe /c `"timeout /t 2 >nul & rmdir /s /q `\`"$Root\`"`"" -ForegroundColor Cyan
    Write-Host "[DryRun] Finished dry run." -ForegroundColor Green
    exit 0
}

# Spawn detached cmd to wait 2 seconds and delete root folder
$cmdArgs = '/c "timeout /t 2 >nul & rmdir /s /q \"' + $Root + '\""'
Start-Process -FilePath "cmd.exe" -ArgumentList $cmdArgs -WindowStyle Hidden
exit 0
