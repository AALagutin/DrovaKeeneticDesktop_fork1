#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Reports Shadow Defender installation status and password validity.

.DESCRIPTION
    Used by deploy.py --check-sd and as a pre-check before --sd-installer.

    Exit codes (parsed by deploy.py):
      0  SD installed, service running, password OK (or no password to verify)
      2  SD not installed                  → safe to run setup with --sd-installer
      3  SD installed but not operational  → needs reboot, or orphaned files (run --uninstall-sd)
      4  SD installed, running, WRONG PASSWORD → update shadow_defender_password in config.json
#>
param(
    [string]$ShadowDefenderPassword = ""
)

$ErrorActionPreference = "SilentlyContinue"
$ProgressPreference    = "SilentlyContinue"

$CMDTOOL = "C:\Program Files\Shadow Defender\CmdTool.exe"
$SD_DIR  = "C:\Program Files\Shadow Defender"

$dirExists  = Test-Path $SD_DIR
$toolExists = Test-Path $CMDTOOL
$svc        = Get-Service -Name "ShadowDefender*" -ErrorAction SilentlyContinue |
              Select-Object -First 1
$svcRunning = ($null -ne $svc -and $svc.Status -eq "Running")

# --- Not installed at all ---
if (-not $dirExists -and -not $toolExists) {
    Write-Host "  SD: not installed" -ForegroundColor Gray
    exit 2
}

# --- Orphaned files: directory exists but CmdTool missing ---
if ($dirExists -and -not $toolExists) {
    Write-Host "  SD: orphaned files in '$SD_DIR' (no CmdTool.exe, no service) — run --uninstall-sd" -ForegroundColor Yellow
    exit 3
}

# --- CmdTool.exe present but service not running ---
if (-not $svcRunning) {
    $svcName = if ($svc) { "'$($svc.Name)' ($($svc.Status))" } else { "none registered" }
    Write-Host "  SD: installed / service $svcName — reboot required to activate driver" -ForegroundColor Yellow
    exit 3
}

# --- Installed and service running — verify password ---
if ($ShadowDefenderPassword -eq "") {
    Write-Host "  SD: installed / service running / no password configured in config" -ForegroundColor Green
    exit 0
}

$proc = Start-Process -FilePath $CMDTOOL `
    -ArgumentList "/pwd:`"$ShadowDefenderPassword`" /list /now" `
    -Wait -PassThru -NoNewWindow `
    -RedirectStandardOutput "$env:TEMP\drova_sd_chk_out.txt" `
    -RedirectStandardError  "$env:TEMP\drova_sd_chk_err.txt"
Remove-Item "$env:TEMP\drova_sd_chk_out.txt","$env:TEMP\drova_sd_chk_err.txt" -ErrorAction SilentlyContinue

if ($proc.ExitCode -eq 0) {
    Write-Host "  SD: installed / service running / password OK" -ForegroundColor Green
    exit 0
} else {
    Write-Host "  SD: installed / service running / WRONG PASSWORD (CmdTool exit $($proc.ExitCode))" -ForegroundColor Red
    exit 4
}
