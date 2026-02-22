#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Silently uninstalls Shadow Defender (any install method).

.DESCRIPTION
    Priority order:
      1. NSIS silent uninstaller: looks for unins*.exe in the SD directory.
      2. WMI uninstall: Win32_Product lookup.
      3. Manual force cleanup:
           - Kill all SD processes
           - sc.exe delete all SD services (WMI-based, catches unregistered drivers)
           - Remove the SD program directory (takeown + icacls if needed)
           - Remove SD uninstall registry keys (both 64-bit and WOW6432Node)

    Use deploy.py --uninstall-sd to push and run this script on all GamePCs.
#>

$ErrorActionPreference = "SilentlyContinue"
$ProgressPreference    = "SilentlyContinue"

$SD_DIR  = "C:\Program Files\Shadow Defender"
$CMDTOOL = "$SD_DIR\CmdTool.exe"

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host " Shadow Defender Uninstall  -  $env:COMPUTERNAME"  -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""

# --- Check if anything to do ---
if (-not (Test-Path $CMDTOOL) -and -not (Test-Path $SD_DIR)) {
    Write-Host "  Shadow Defender is not installed. Nothing to do." -ForegroundColor Green
    exit 0
}
Write-Host "  Found: $SD_DIR" -ForegroundColor Gray

# --- Stop service via Get-Service (fast path) ---
$svc = Get-Service -Name "ShadowDefender*" -ErrorAction SilentlyContinue |
       Select-Object -First 1
if ($svc) {
    Write-Host "  Service: $($svc.Name) / Status: $($svc.Status)" -ForegroundColor Gray
    if ($svc.Status -eq "Running") {
        Write-Host "  Stopping service..." -ForegroundColor Gray
        Stop-Service -Name $svc.Name -Force -ErrorAction SilentlyContinue
        Write-Host "  Service stopped." -ForegroundColor Green
    }
} else {
    Write-Host "  No service via Get-Service (driver may not be registered)." -ForegroundColor Gray
}

# ---------------------------------------------------------------------------
# Method 1: NSIS uninstaller (any unins*.exe in the SD directory)
# ---------------------------------------------------------------------------
$uninstBin = Get-ChildItem -Path $SD_DIR -Filter "unins*.exe" -ErrorAction SilentlyContinue |
             Select-Object -First 1
if ($uninstBin) {
    Write-Host "  Running NSIS uninstaller: $($uninstBin.FullName) /S ..." -ForegroundColor Gray
    $proc = Start-Process -FilePath $uninstBin.FullName -ArgumentList "/S" -Wait -PassThru
    Write-Host "  Uninstaller exit code: $($proc.ExitCode)" -ForegroundColor $(if ($proc.ExitCode -eq 0) {"Green"} else {"Yellow"})
    if ($proc.ExitCode -eq 0) {
        Write-Host "  REBOOT REQUIRED to unload the kernel driver." -ForegroundColor Yellow
        Write-Host "  Done." -ForegroundColor Green
        Write-Host ""
        exit 0
    }
    Write-Host "  NSIS uninstall did not exit cleanly, falling through to manual cleanup." -ForegroundColor Yellow
}

# ---------------------------------------------------------------------------
# Method 2: WMI uninstall
# ---------------------------------------------------------------------------
Write-Host "  Trying WMI uninstall..." -ForegroundColor Gray
$product = Get-WmiObject -Class Win32_Product -ErrorAction SilentlyContinue |
           Where-Object { $_.Name -like "*Shadow Defender*" }
if ($product) {
    $result = $product.Uninstall()
    if ($result.ReturnValue -eq 0) {
        Write-Host "  WMI uninstall succeeded." -ForegroundColor Green
        Write-Host "  REBOOT REQUIRED to unload the kernel driver." -ForegroundColor Yellow
        Write-Host "  Done." -ForegroundColor Green
        Write-Host ""
        exit 0
    }
    Write-Host "  WMI uninstall returned: $($result.ReturnValue) — falling through to manual cleanup." -ForegroundColor Yellow
} else {
    Write-Host "  No WMI product entry found." -ForegroundColor Gray
}

# ---------------------------------------------------------------------------
# Method 3: Manual force cleanup
# (handles SD installed without a proper installer / orphaned files)
# ---------------------------------------------------------------------------
Write-Host "  Performing manual force cleanup..." -ForegroundColor Yellow

# 3a. Kill all SD-related processes
$sdProcPatterns = @("Shadow*", "ShadowSrv*", "ShadowUI*", "CmdTool*")
foreach ($pat in $sdProcPatterns) {
    Get-Process -Name $pat -ErrorAction SilentlyContinue | ForEach-Object {
        Write-Host "  Killing process: $($_.Name) (PID $($_.Id))" -ForegroundColor Gray
        $_.Kill()
    }
}
Start-Sleep -Milliseconds 500

# 3b. Delete all services whose binary path lives inside the SD directory
#     Uses WMI because some drivers may not appear in Get-Service.
$sdServices = Get-WmiObject Win32_Service -ErrorAction SilentlyContinue |
              Where-Object { $_.PathName -like "*Shadow Defender*" -or $_.Name -like "*Shadow*" }
foreach ($s in $sdServices) {
    Write-Host "  Removing service: $($s.Name)" -ForegroundColor Gray
    & sc.exe stop   $s.Name 2>&1 | Out-Null
    & sc.exe delete $s.Name 2>&1 | Out-Null
}

# 3c. Remove uninstall registry keys
$uninstBases = @(
    "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
    "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"
)
foreach ($base in $uninstBases) {
    if (-not (Test-Path $base)) { continue }
    Get-ChildItem $base -ErrorAction SilentlyContinue | ForEach-Object {
        $disp = (Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue).DisplayName
        if ($disp -like "*Shadow Defender*") {
            Write-Host "  Removing uninstall key: $($_.PSPath)" -ForegroundColor Gray
            Remove-Item $_.PSPath -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

# 3d. Delete SD program directory
if (Test-Path $SD_DIR) {
    Write-Host "  Removing directory: $SD_DIR ..." -ForegroundColor Gray
    # First attempt — may fail if a driver file is locked
    Remove-Item $SD_DIR -Recurse -Force -ErrorAction SilentlyContinue
    if (Test-Path $SD_DIR) {
        # Take ownership and grant full control, then retry
        & takeown.exe /f "$SD_DIR" /r /d y 2>&1 | Out-Null
        & icacls.exe  "$SD_DIR" /grant "Administrators:F" /t 2>&1 | Out-Null
        & cmd.exe /c "rmdir /s /q `"$SD_DIR`"" 2>&1 | Out-Null
    }
    if (Test-Path $SD_DIR) {
        Write-Host "  Directory still present — a driver file may be locked until reboot." -ForegroundColor Yellow
    } else {
        Write-Host "  Directory removed." -ForegroundColor Green
    }
}

# --- Final status ---
Write-Host ""
if (Test-Path $CMDTOOL) {
    Write-Host "  CmdTool.exe still present (locked driver file — will be gone after reboot)." -ForegroundColor Yellow
} else {
    Write-Host "  Shadow Defender files removed." -ForegroundColor Green
}

Write-Host "  REBOOT REQUIRED to fully unload the kernel driver." -ForegroundColor Yellow
Write-Host "  Done." -ForegroundColor Green
Write-Host ""
exit 0
