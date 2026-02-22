#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Removes all Drova Keenetic restrictions left behind after a force-killed client session.

.DESCRIPTION
    Reverses the registry patches (PatchWindowsSettings) and firewall rules
    (PatchNetworkHardening) applied by drova_desktop_keenetic/common/patch.py.

    Run this on Game PCs where:
      - The client was force-killed (AfterDisconnect never ran), AND/OR
      - Shadow Defender was already removed so restrictions were not discarded on reboot.

    This script runs as SYSTEM via PsExec, so HKCU patches are addressed through
    HKU\{UserSID}\... for every interactive user found on the machine.
#>

$ErrorActionPreference = "SilentlyContinue"
$ProgressPreference    = "SilentlyContinue"

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host " Drova Restriction Removal  -  $env:COMPUTERNAME"  -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""

# ---------------------------------------------------------------------------
# 1. Locate all interactive user SIDs in HKU
#    (skip SYSTEM S-1-5-18, LocalService S-1-5-19, NetworkService S-1-5-20,
#     and the _Classes suffix hives)
# ---------------------------------------------------------------------------
$userSIDs = Get-ChildItem "Registry::HKEY_USERS" -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match 'S-1-5-21-' -and $_.Name -notmatch '_Classes$' } |
            ForEach-Object { $_.Name -replace '^HKEY_USERS\\', '' }

if ($userSIDs) {
    Write-Host "  Interactive user SIDs: $($userSIDs -join ', ')" -ForegroundColor Gray
} else {
    Write-Host "  No interactive user sessions found in HKU — skipping per-user registry cleanup." -ForegroundColor Yellow
}

# Paths from PatchWindowsSettings (relative to HKU\{SID})
$explorerPolicyPath = "Software\Microsoft\Windows\CurrentVersion\Policies\Explorer"

foreach ($sid in $userSIDs) {
    $hku = "Registry::HKEY_USERS\$sid"
    Write-Host ""
    Write-Host "  --- User SID: $sid ---" -ForegroundColor White

    # DisableCMD
    $p = "$hku\Software\Policies\Microsoft\Windows\System"
    Remove-ItemProperty -Path $p -Name "DisableCMD" -Force -ErrorAction SilentlyContinue
    Write-Host "    [-] DisableCMD" -ForegroundColor Gray

    # DisableTaskMgr + DisableGpedit
    $p = "$hku\Software\Microsoft\Windows\CurrentVersion\Policies\System"
    Remove-ItemProperty -Path $p -Name "DisableTaskMgr" -Force -ErrorAction SilentlyContinue
    Remove-ItemProperty -Path $p -Name "DisableGpedit"  -Force -ErrorAction SilentlyContinue
    Write-Host "    [-] DisableTaskMgr, DisableGpedit" -ForegroundColor Gray

    # VBScript restriction
    $p = "$hku\Software\Policies\Microsoft\Windows Script Host"
    Remove-ItemProperty -Path $p -Name "Enabled" -Force -ErrorAction SilentlyContinue
    Write-Host "    [-] VBScript Enabled=0 restriction" -ForegroundColor Gray

    # Explorer policy: power/logoff buttons
    $ep = "$hku\$explorerPolicyPath"
    foreach ($name in @("NoClose", "StartMenuLogoff", "ShutdownWithoutLogon", "NoLogoff")) {
        Remove-ItemProperty -Path $ep -Name $name -Force -ErrorAction SilentlyContinue
    }
    Write-Host "    [-] NoClose / StartMenuLogoff / ShutdownWithoutLogon / NoLogoff" -ForegroundColor Gray

    # DisallowRun flag + numbered app entries applied directly to Explorer key
    Remove-ItemProperty -Path $ep -Name "DisallowRun" -Force -ErrorAction SilentlyContinue
    for ($i = 0; $i -lt 25; $i++) {
        Remove-ItemProperty -Path $ep -Name "$i" -Force -ErrorAction SilentlyContinue
    }
    # Also remove DisallowRun subkey in case it was created as a proper subkey
    Remove-Item -Path "$ep\DisallowRun" -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "    [-] DisallowRun + blocked app list" -ForegroundColor Gray

    # MMC restriction
    $p = "$hku\Software\Policies\Microsoft\MMC"
    Remove-ItemProperty -Path $p -Name "RestrictToPermittedSnapins" -Force -ErrorAction SilentlyContinue
    Write-Host "    [-] MMC RestrictToPermittedSnapins" -ForegroundColor Gray
}

# ---------------------------------------------------------------------------
# 2. HKLM restriction (runs as SYSTEM, so normal HKLM: path works fine)
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "  --- HKLM restrictions ---" -ForegroundColor White
$hklmSys = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System"
Remove-ItemProperty -Path $hklmSys -Name "HideFastUserSwitching" -Force -ErrorAction SilentlyContinue
Write-Host "    [-] HideFastUserSwitching" -ForegroundColor Gray

# ---------------------------------------------------------------------------
# 3. Firewall rules (PatchNetworkHardening)
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "  --- Firewall restrictions ---" -ForegroundColor White

& netsh advfirewall firewall delete rule name="Block SMB Out"     2>&1 | Out-Null
Write-Host "    [-] Firewall rule: Block SMB Out" -ForegroundColor Gray

& netsh advfirewall firewall delete rule name="Block NetBIOS Out" 2>&1 | Out-Null
Write-Host "    [-] Firewall rule: Block NetBIOS Out" -ForegroundColor Gray

& netsh advfirewall firewall set rule group="Network Discovery" new enable=Yes 2>&1 | Out-Null
Write-Host "    [+] Network Discovery re-enabled" -ForegroundColor Gray

# Restart network discovery services
foreach ($svc in @("FDResPub", "SSDPSRV", "fdPHost")) {
    & sc.exe config $svc start= demand 2>&1 | Out-Null
    & sc.exe start  $svc         2>&1 | Out-Null
    Write-Host "    [+] Service started: $svc" -ForegroundColor Gray
}

# ---------------------------------------------------------------------------
# 4. Force group policy refresh so changes take effect in the current session
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "  Running gpupdate /force ..." -ForegroundColor White
& gpupdate.exe /target:user /force /quiet 2>&1 | Out-Null
Write-Host "    gpupdate done." -ForegroundColor Green

Write-Host ""
Write-Host "  All restrictions removed successfully." -ForegroundColor Green
Write-Host "  Done." -ForegroundColor Green
Write-Host ""
exit 0
