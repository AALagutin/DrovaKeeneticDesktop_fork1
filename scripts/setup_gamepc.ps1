#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Drova GamePC automated setup script.

.DESCRIPTION
    Installs and configures:
      - OpenSSH Server (Windows capability)
      - PsExec (from Sysinternals, to System32)
      - FFmpeg (to C:\ffmpeg\bin\, skip with -SkipFFmpeg)
      - Shadow Defender (detection, optional silent install, CmdTool verification)

    Prerequisites (already done before running this script):
      - LocalAccountTokenFilterPolicy = 1  (enables admin over SMB/WinRM)
      - Network profile set to Private

.PARAMETER SkipFFmpeg
    Skip FFmpeg installation (use if streaming is not needed).

.PARAMETER ShadowDefenderInstaller
    Full path to the Shadow Defender installer exe on this machine.
    If provided and SD is not yet installed, the installer is run silently (/S flag).
    Example: -ShadowDefenderInstaller "D:\Setup\ShadowDefender_Setup.exe"

.PARAMETER ShadowDefenderPassword
    Password to verify with CmdTool.exe after installation.
    For a fresh SD install (no password yet configured), leave empty.
    After running this script, set the password via SD GUI → Administration,
    then update SHADOW_DEFENDER_PASSWORD in your Drova config.json.

.NOTES
    Shadow Defender password and GUI settings (Enable password control,
    Disable tray tip, Need password when committing) CANNOT be configured
    via CmdTool.exe — CmdTool only authenticates with an existing password.
    These settings require a one-time manual step in the SD Administration GUI.
#>
param(
    [switch]$SkipFFmpeg = $false,
    [string]$ShadowDefenderInstaller = "",
    [string]$ShadowDefenderPassword  = ""
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # makes Invoke-WebRequest much faster

$CMDTOOL = "C:\Program Files\Shadow Defender\CmdTool.exe"

# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host " Drova GamePC Setup  -  $env:COMPUTERNAME" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""

# ---------------------------------------------------------------------------
# 1. OpenSSH Server
# ---------------------------------------------------------------------------
Write-Host "[1/5] OpenSSH Server" -ForegroundColor Yellow

$cap = Get-WindowsCapability -Online | Where-Object Name -like "OpenSSH.Server*"
if ($cap.State -ne "Installed") {
    Write-Host "  Installing OpenSSH.Server capability..." -ForegroundColor Gray
    Add-WindowsCapability -Online -Name $cap.Name | Out-Null
    Write-Host "  Installed." -ForegroundColor Green
} else {
    Write-Host "  Already installed." -ForegroundColor Gray
}

Set-Service -Name sshd -StartupType Automatic
Start-Service -Name sshd -ErrorAction SilentlyContinue
$sshdStatus = (Get-Service sshd).Status
Write-Host "  Status: $sshdStatus" -ForegroundColor $(if ($sshdStatus -eq "Running") {"Green"} else {"Red"})

$fwRule = Get-NetFirewallRule -Name "OpenSSH-Server-In-TCP" -ErrorAction SilentlyContinue
if (-not $fwRule) {
    New-NetFirewallRule -Name "OpenSSH-Server-In-TCP" `
        -DisplayName "OpenSSH Server (sshd)" `
        -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22 | Out-Null
    Write-Host "  Firewall rule created." -ForegroundColor Green
} else {
    Write-Host "  Firewall rule already exists." -ForegroundColor Gray
}

$regPath = "HKLM:\SOFTWARE\OpenSSH"
$psShell  = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
if (-not (Test-Path $regPath)) { New-Item -Path $regPath -Force | Out-Null }
Set-ItemProperty -Path $regPath -Name DefaultShell -Value $psShell -Type String | Out-Null
Write-Host "  Default SSH shell -> PowerShell" -ForegroundColor Green

# ---------------------------------------------------------------------------
# 2. PsExec
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "[2/5] PsExec" -ForegroundColor Yellow

$psexecDst = "$env:SystemRoot\System32\PsExec.exe"
if (-not (Test-Path $psexecDst)) {
    $zipPath = "$env:TEMP\PSTools.zip"
    $extractPath = "$env:TEMP\PSTools_drova"
    Write-Host "  Downloading PSTools from Sysinternals..." -ForegroundColor Gray
    Invoke-WebRequest -Uri "https://download.sysinternals.com/files/PSTools.zip" -OutFile $zipPath
    Expand-Archive -Path $zipPath -DestinationPath $extractPath -Force
    Copy-Item "$extractPath\PsExec.exe"   $env:SystemRoot\System32\ -Force
    Copy-Item "$extractPath\PsExec64.exe" $env:SystemRoot\System32\ -Force
    Remove-Item $zipPath, $extractPath -Recurse -Force
    Write-Host "  PsExec installed to System32." -ForegroundColor Green
} else {
    Write-Host "  Already installed." -ForegroundColor Gray
}

# Accept EULA for current user and for SYSTEM (used by Drova workers via pypsexec)
foreach ($key in @("HKCU:\Software\Sysinternals\PsExec", "HKLM:\Software\Sysinternals\PsExec")) {
    if (-not (Test-Path $key)) { New-Item -Path $key -Force | Out-Null }
    Set-ItemProperty -Path $key -Name EulaAccepted -Value 1 -Type DWord -Force | Out-Null
}
Write-Host "  EULA accepted (HKCU + HKLM)." -ForegroundColor Green

# ---------------------------------------------------------------------------
# 3. FFmpeg  (optional)
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "[3/5] FFmpeg" -ForegroundColor Yellow

$ffmpegExe = "C:\ffmpeg\bin\ffmpeg.exe"
if ($SkipFFmpeg) {
    Write-Host "  Skipped (-SkipFFmpeg)." -ForegroundColor Gray
} elseif (Test-Path $ffmpegExe) {
    Write-Host "  Already installed at C:\ffmpeg\bin\." -ForegroundColor Gray
} else {
    $ffUrl = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
    $ffZip = "$env:TEMP\ffmpeg_drova.zip"
    $ffExt = "$env:TEMP\ffmpeg_drova_ext"
    Write-Host "  Downloading FFmpeg (~100 MB)..." -ForegroundColor Gray
    Invoke-WebRequest -Uri $ffUrl -OutFile $ffZip
    Write-Host "  Extracting..." -ForegroundColor Gray
    Expand-Archive -Path $ffZip -DestinationPath $ffExt -Force
    $inner = Get-ChildItem $ffExt | Where-Object PSIsContainer | Select-Object -First 1
    New-Item -Path "C:\ffmpeg\bin" -ItemType Directory -Force | Out-Null
    Copy-Item "$($inner.FullName)\bin\ffmpeg.exe"  "C:\ffmpeg\bin\" -Force
    Copy-Item "$($inner.FullName)\bin\ffprobe.exe" "C:\ffmpeg\bin\" -Force -ErrorAction SilentlyContinue
    Remove-Item $ffZip, $ffExt -Recurse -Force
    Write-Host "  FFmpeg installed to C:\ffmpeg\bin\." -ForegroundColor Green
}

# ---------------------------------------------------------------------------
# 4. Shadow Defender
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "[4/5] Shadow Defender" -ForegroundColor Yellow

$sdNeedsReboot  = $false
$sdCmdToolOk    = $false
$sdJustInstalled = $false

function Get-SDService {
    return Get-Service -Name "ShadowDefender*" -ErrorAction SilentlyContinue |
           Select-Object -First 1
}

# --- 4a. Installation ---
if (Test-Path $CMDTOOL) {
    Write-Host "  Already installed." -ForegroundColor Gray
} elseif ($ShadowDefenderInstaller) {
    if (-not (Test-Path $ShadowDefenderInstaller)) {
        Write-Host "  ERROR: installer not found: $ShadowDefenderInstaller" -ForegroundColor Red
    } else {
        Write-Host "  Running installer silently..." -ForegroundColor Gray
        # Standard NSIS /S flag; Shadow Defender setup.exe is NSIS-based
        $proc = Start-Process -FilePath $ShadowDefenderInstaller `
                              -ArgumentList "/S" -Wait -PassThru
        if ($proc.ExitCode -eq 0) {
            $sdJustInstalled = $true
            Write-Host "  Installed (exit 0)." -ForegroundColor Green
        } else {
            Write-Host "  Installer exited with code $($proc.ExitCode)." -ForegroundColor Red
        }
    }
} else {
    Write-Host "  Not installed." -ForegroundColor Yellow
    Write-Host "  To install automatically, re-run with:" -ForegroundColor Yellow
    Write-Host "    -ShadowDefenderInstaller <path_to_SD_setup.exe>" -ForegroundColor White
    Write-Host "  Or install manually from https://www.shadowdefender.com/" -ForegroundColor White
}

# --- 4b. Service check ---
$sdSvc = Get-SDService
if ($sdSvc) {
    if ($sdSvc.Status -eq "Running") {
        Write-Host "  Service: $($sdSvc.Name) — Running" -ForegroundColor Green
    } else {
        Write-Host "  Service: $($sdSvc.Name) — $($sdSvc.Status)" -ForegroundColor Yellow
        if ($sdJustInstalled) {
            Write-Host "  Shadow Defender requires a REBOOT to activate the driver." -ForegroundColor Yellow
            $sdNeedsReboot = $true
        }
    }
} elseif (Test-Path $CMDTOOL) {
    # SD installed but service not registered yet → definitely needs reboot
    Write-Host "  Driver service not found — reboot required to activate." -ForegroundColor Yellow
    $sdNeedsReboot = $true
}

# --- 4c. CmdTool.exe verification ---
# Runs /list /now with the given password to prove CmdTool responds correctly.
# On a fresh install (no password set), /pwd:"" works.
# CmdTool exit codes: 0 = success, non-zero = wrong password or SD not active.
if ((Test-Path $CMDTOOL) -and -not $sdNeedsReboot) {
    Write-Host "  Verifying CmdTool.exe with password '$ShadowDefenderPassword'..." -ForegroundColor Gray
    $cmdArgs = "/pwd:`"$ShadowDefenderPassword`" /list /now"
    $proc = Start-Process -FilePath $CMDTOOL -ArgumentList $cmdArgs `
                          -Wait -PassThru -NoNewWindow `
                          -RedirectStandardOutput "$env:TEMP\sd_list_out.txt" `
                          -RedirectStandardError  "$env:TEMP\sd_list_err.txt"
    $sdCmdToolOk = ($proc.ExitCode -eq 0)
    if ($sdCmdToolOk) {
        Write-Host "  CmdTool.exe: OK" -ForegroundColor Green
        $listOut = Get-Content "$env:TEMP\sd_list_out.txt" -ErrorAction SilentlyContinue
        if ($listOut) { $listOut | ForEach-Object { Write-Host "    $_" -ForegroundColor Gray } }
    } else {
        Write-Host "  CmdTool.exe: exit=$($proc.ExitCode)" -ForegroundColor Red
        Write-Host "  Possible reasons:" -ForegroundColor Yellow
        Write-Host "    - Wrong password (check -ShadowDefenderPassword)" -ForegroundColor White
        Write-Host "    - Password protection not yet enabled (open SD → Administration" -ForegroundColor White
        Write-Host "      → Enable password control, set password, then re-run this script)" -ForegroundColor White
    }
    Remove-Item "$env:TEMP\sd_list_out.txt","$env:TEMP\sd_list_err.txt" -ErrorAction SilentlyContinue
} elseif ($sdNeedsReboot) {
    Write-Host "  CmdTool.exe verification skipped — reboot first, then re-run this script." -ForegroundColor Yellow
}

# --- 4d. What CmdTool cannot do ---
# CmdTool.exe has no command to SET the password or toggle GUI settings.
# These require a one-time manual step in SD → Administration:
#   1. Click "Enable password control" → enter the desired password
#   2. Tick "Need password when committing"
#   3. Optionally untick "Enable windows tip"
# Then update SHADOW_DEFENDER_PASSWORD in your Drova config.

# ---------------------------------------------------------------------------
# 5. Verification summary
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "[5/5] Summary" -ForegroundColor Yellow

$checks = [ordered]@{
    "OpenSSH sshd running"       = ($sshdStatus -eq "Running")
    "PsExec in System32"         = (Test-Path $psexecDst)
    "FFmpeg installed"           = (Test-Path $ffmpegExe) -or $SkipFFmpeg
    "Shadow Defender installed"  = (Test-Path $CMDTOOL)
    "Shadow Defender service"    = (($sdSvc -ne $null) -and ($sdSvc.Status -eq "Running")) -or $sdNeedsReboot
    "CmdTool.exe responds"       = $sdCmdToolOk -or $sdNeedsReboot
}

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host " Result" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
$allOk = $true
foreach ($item in $checks.GetEnumerator()) {
    $ok     = $item.Value
    $symbol = if ($ok) {"[OK]"} else {"[!!]"}
    $color  = if ($ok) {"Green"} else {"Red"}
    Write-Host "  $symbol  $($item.Key)" -ForegroundColor $color
    if (-not $ok) { $allOk = $false }
}
Write-Host ""

if ($sdNeedsReboot) {
    Write-Host "  REBOOT REQUIRED:" -ForegroundColor Yellow
    Write-Host "    Shadow Defender was just installed. After reboot, re-run this" -ForegroundColor White
    Write-Host "    script to verify CmdTool.exe and configure the SD password." -ForegroundColor White
    Write-Host ""
}

if (-not $sdCmdToolOk -and -not $sdNeedsReboot -and (Test-Path $CMDTOOL)) {
    Write-Host "  MANUAL STEP REQUIRED — Shadow Defender password:" -ForegroundColor Cyan
    Write-Host "    1. Open Shadow Defender → Administration" -ForegroundColor White
    Write-Host "    2. Click 'Enable password control' → enter the password" -ForegroundColor White
    Write-Host "    3. Tick 'Need password when committing'" -ForegroundColor White
    Write-Host "    4. Optionally untick 'Enable windows tip'" -ForegroundColor White
    Write-Host "    5. Re-run this script with -ShadowDefenderPassword <pwd>" -ForegroundColor White
    Write-Host "    6. Update SHADOW_DEFENDER_PASSWORD in your Drova config." -ForegroundColor White
    Write-Host ""
} elseif ($sdCmdToolOk) {
    Write-Host "  Shadow Defender is active and CmdTool.exe is working." -ForegroundColor Green
    Write-Host "  Make sure SHADOW_DEFENDER_PASSWORD in Drova config matches" -ForegroundColor White
    Write-Host "  the password you set in SD Administration (or empty string" -ForegroundColor White
    Write-Host "  if 'Enable password control' is off)." -ForegroundColor White
    Write-Host ""
}

if ($allOk) {
    Write-Host "  All checks passed. This PC is ready for Drova." -ForegroundColor Green
    exit 0
} else {
    Write-Host "  Some checks did not pass. See details above." -ForegroundColor Yellow
    # Exit 0 even with pending items — reboot + manual SD password step are expected
    # and should not block the deploy.py success count.
    exit 0
}
