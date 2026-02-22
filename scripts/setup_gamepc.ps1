#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Drova GamePC automated setup script.

.DESCRIPTION
    Installs and configures:
      - OpenSSH Server (Windows capability)
      - PsExec (from Sysinternals, to System32)
      - FFmpeg (to C:\ffmpeg\bin\, skip with -SkipFFmpeg)

    Prerequisites (already done before running this script):
      - LocalAccountTokenFilterPolicy = 1  (enables admin over SMB/WinRM)
      - Network profile set to Private

.PARAMETER SkipFFmpeg
    Skip FFmpeg installation (use if streaming is not needed).
#>
param(
    [switch]$SkipFFmpeg = $false
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # makes Invoke-WebRequest much faster

# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host " Drova GamePC Setup  -  $env:COMPUTERNAME" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""

# ---------------------------------------------------------------------------
# 1. OpenSSH Server
# ---------------------------------------------------------------------------
Write-Host "[1/4] OpenSSH Server" -ForegroundColor Yellow

$cap = Get-WindowsCapability -Online | Where-Object Name -like "OpenSSH.Server*"
if ($cap.State -ne "Installed") {
    Write-Host "  Installing OpenSSH.Server capability..." -ForegroundColor Gray
    Add-WindowsCapability -Online -Name $cap.Name | Out-Null
    Write-Host "  Installed." -ForegroundColor Green
} else {
    Write-Host "  Already installed." -ForegroundColor Gray
}

Set-Service -Name sshd -StartupType Automatic
Start-Service -Name sshd -ErrorAction SilentlyContinue   # may already be running
$sshdStatus = (Get-Service sshd).Status
Write-Host "  Status: $sshdStatus" -ForegroundColor $(if ($sshdStatus -eq "Running") {"Green"} else {"Red"})

# Firewall: allow SSH on all profiles (private is already open, but be explicit)
$fwRule = Get-NetFirewallRule -Name "OpenSSH-Server-In-TCP" -ErrorAction SilentlyContinue
if (-not $fwRule) {
    New-NetFirewallRule -Name "OpenSSH-Server-In-TCP" `
        -DisplayName "OpenSSH Server (sshd)" `
        -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22 | Out-Null
    Write-Host "  Firewall rule created." -ForegroundColor Green
} else {
    Write-Host "  Firewall rule already exists." -ForegroundColor Gray
}

# Set PowerShell as the default SSH shell (asyncssh works with both cmd and PS,
# but PS gives richer output for registry queries used by helpers.py)
$regPath = "HKLM:\SOFTWARE\OpenSSH"
$psShell  = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
if (-not (Test-Path $regPath)) { New-Item -Path $regPath -Force | Out-Null }
Set-ItemProperty -Path $regPath -Name DefaultShell -Value $psShell -Type String | Out-Null
Write-Host "  Default SSH shell -> PowerShell" -ForegroundColor Green

# ---------------------------------------------------------------------------
# 2. PsExec
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "[2/4] PsExec" -ForegroundColor Yellow

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

# Pre-accept EULA so PsExec doesn't block waiting for interactive confirmation
$eulaKey = "HKCU:\Software\Sysinternals\PsExec"
if (-not (Test-Path $eulaKey)) { New-Item -Path $eulaKey -Force | Out-Null }
Set-ItemProperty -Path $eulaKey -Name EulaAccepted -Value 1 -Type DWord -Force | Out-Null
# Also accept EULA system-wide (for SYSTEM account, used by Drova workers)
$eulaKeyLM = "HKLM:\Software\Sysinternals\PsExec"
if (-not (Test-Path $eulaKeyLM)) { New-Item -Path $eulaKeyLM -Force | Out-Null }
Set-ItemProperty -Path $eulaKeyLM -Name EulaAccepted -Value 1 -Type DWord -Force | Out-Null
Write-Host "  EULA accepted." -ForegroundColor Green

# ---------------------------------------------------------------------------
# 3. FFmpeg  (optional)
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "[3/4] FFmpeg" -ForegroundColor Yellow

$ffmpegExe = "C:\ffmpeg\bin\ffmpeg.exe"
if ($SkipFFmpeg) {
    Write-Host "  Skipped (--SkipFFmpeg)." -ForegroundColor Gray
} elseif (Test-Path $ffmpegExe) {
    Write-Host "  Already installed at C:\ffmpeg\bin\." -ForegroundColor Gray
} else {
    # BtbN GPL essentials build (~45 MB, contains only ffmpeg/ffprobe/ffplay)
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
# 4. Verification summary
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "[4/4] Verification" -ForegroundColor Yellow

$results = @{
    "OpenSSH sshd running" = ((Get-Service sshd).Status -eq "Running")
    "PsExec in System32"   = (Test-Path $psexecDst)
    "FFmpeg installed"     = (Test-Path $ffmpegExe) -or $SkipFFmpeg
}

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host " Result" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
$allOk = $true
foreach ($item in $results.GetEnumerator()) {
    $ok = $item.Value
    $symbol = if ($ok) {"[OK]"} else {"[!!]"}
    $color  = if ($ok) {"Green"} else {"Red"}
    Write-Host "  $symbol  $($item.Key)" -ForegroundColor $color
    if (-not $ok) { $allOk = $false }
}
Write-Host ""

if ($allOk) {
    Write-Host "  All checks passed. This PC is ready for Drova." -ForegroundColor Green
    Write-Host ""
    Write-Host "  Remaining manual step:" -ForegroundColor Cyan
    Write-Host "    Install and activate Shadow Defender, set the password," -ForegroundColor White
    Write-Host "    then update SHADOW_DEFENDER_PASSWORD in your Drova config." -ForegroundColor White
    exit 0
} else {
    Write-Host "  Some checks FAILED. Review the output above." -ForegroundColor Red
    exit 1
}
