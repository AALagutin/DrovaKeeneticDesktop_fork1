#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Silently uninstalls Shadow Defender.

.DESCRIPTION
    Stops the Shadow Defender service, then runs the NSIS silent uninstaller
    (unins000.exe /S).  Falls back to WMI if the uninstaller binary is missing.
    A reboot is required after uninstall to remove the kernel driver.

    Use deploy.py --uninstall-sd to push and run this script on all GamePCs.
#>

$ErrorActionPreference = "Stop"
$ProgressPreference    = "SilentlyContinue"

$SD_DIR  = "C:\Program Files\Shadow Defender"
$UNINST  = "$SD_DIR\unins000.exe"
$CMDTOOL = "$SD_DIR\CmdTool.exe"

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host " Shadow Defender Uninstall  -  $env:COMPUTERNAME"  -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""

# --- Check if installed ---
if (-not (Test-Path $CMDTOOL)) {
    Write-Host "  Shadow Defender is not installed. Nothing to do." -ForegroundColor Green
    exit 0
}
Write-Host "  Found: $SD_DIR" -ForegroundColor Gray

# --- Stop service ---
$svc = Get-Service -Name "ShadowDefender*" -ErrorAction SilentlyContinue |
       Select-Object -First 1
if ($svc) {
    Write-Host "  Service: $($svc.Name) / Status: $($svc.Status)" -ForegroundColor Gray
    if ($svc.Status -eq "Running") {
        Write-Host "  Stopping service..." -ForegroundColor Gray
        try {
            Stop-Service -Name $svc.Name -Force -ErrorAction Stop
            Write-Host "  Service stopped." -ForegroundColor Green
        } catch {
            Write-Host "  Warning: could not stop service: $_" -ForegroundColor Yellow
        }
    }
} else {
    Write-Host "  Service not found (driver may not be active)." -ForegroundColor Gray
}

# --- Uninstall ---
if (Test-Path $UNINST) {
    Write-Host "  Running: $UNINST /S ..." -ForegroundColor Gray
    $proc = Start-Process -FilePath $UNINST -ArgumentList "/S" -Wait -PassThru
    if ($proc.ExitCode -eq 0) {
        Write-Host "  Uninstaller finished (exit 0)." -ForegroundColor Green
    } else {
        Write-Host "  Uninstaller exit code: $($proc.ExitCode)" -ForegroundColor Yellow
        Write-Host "  Continuing — some files may still be present until reboot." -ForegroundColor Yellow
    }
} else {
    Write-Host "  unins000.exe not found, trying WMI uninstall..." -ForegroundColor Yellow
    $product = Get-WmiObject -Class Win32_Product -ErrorAction SilentlyContinue |
               Where-Object { $_.Name -like "*Shadow Defender*" }
    if ($product) {
        $result = $product.Uninstall()
        if ($result.ReturnValue -eq 0) {
            Write-Host "  WMI uninstall succeeded." -ForegroundColor Green
        } else {
            Write-Host "  WMI uninstall failed (ReturnValue=$($result.ReturnValue))." -ForegroundColor Red
            exit 1
        }
    } else {
        Write-Host "  ERROR: cannot find uninstaller or WMI product entry." -ForegroundColor Red
        exit 1
    }
}

# --- Post-check ---
if (Test-Path $CMDTOOL) {
    Write-Host ""
    Write-Host "  Files still present (normal — reboot will complete removal)." -ForegroundColor Yellow
} else {
    Write-Host "  Installation directory removed." -ForegroundColor Green
}

Write-Host ""
Write-Host "  REBOOT REQUIRED to unload the kernel driver." -ForegroundColor Yellow
Write-Host "  Done." -ForegroundColor Green
Write-Host ""
exit 0
