# rollback_restrictions.ps1
# Removes all Windows registry restrictions applied by DrovaKeenetic.
# Run locally on the game PC (no SSH needed).
# HKLM keys require elevation; run as Administrator.

[CmdletBinding()]
param()

$ErrorActionPreference = 'SilentlyContinue'

function Remove-RegValue {
    param([string]$Path, [string]$Name)
    if (Test-Path $Path) {
        Remove-ItemProperty -Path $Path -Name $Name -ErrorAction SilentlyContinue
    }
}

Write-Host "=== DrovaKeenetic restriction rollback ===" -ForegroundColor Cyan

# --- CMD ---
Remove-RegValue "HKCU:\Software\Policies\Microsoft\Windows\System" "DisableCMD"
Write-Host "[+] DisableCMD"

# --- Task Manager ---
Remove-RegValue "HKCU:\Software\Microsoft\Windows\CurrentVersion\Policies\System" "DisableTaskMgr"
Write-Host "[+] DisableTaskMgr"

# --- VBScript ---
Remove-RegValue "HKCU:\Software\Policies\Microsoft\Windows Script Host" "Enabled"
Write-Host "[+] VBScript"

# --- Explorer policies ---
$explorerPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Policies\Explorer"
Remove-RegValue $explorerPath "NoClose"
Remove-RegValue $explorerPath "StartMenuLogoff"
Remove-RegValue $explorerPath "ShutdownWithoutLogon"
Remove-RegValue $explorerPath "NoLogoff"
Remove-RegValue $explorerPath "DisallowRun"
Write-Host "[+] Explorer (NoClose, Logoff, Shutdown, DisallowRun flag)"

# --- Blocked application list (numeric values 0..16 in Explorer key) ---
for ($i = 0; $i -le 16; $i++) {
    Remove-RegValue $explorerPath "$i"
}
Write-Host "[+] Blocked apps list (0..16)"

# --- DisallowRun subkey (Windows standard location, in case it was also populated) ---
$disallowRunKey = "$explorerPath\DisallowRun"
if (Test-Path $disallowRunKey) {
    Remove-Item -Path $disallowRunKey -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "[+] DisallowRun subkey"
}

# --- Group Policy Editor ---
Remove-RegValue "HKCU:\Software\Microsoft\Windows\CurrentVersion\Policies\System" "DisableGpedit"
Write-Host "[+] DisableGpedit"

# --- MMC ---
Remove-RegValue "HKCU:\Software\Policies\Microsoft\MMC" "RestrictToPermittedSnapins"
Write-Host "[+] MMC RestrictToPermittedSnapins"

# --- Fast User Switching (HKLM - requires Administrator) ---
$currentPrincipal = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
$isAdmin = $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if ($isAdmin) {
    Remove-RegValue "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" "HideFastUserSwitching"
    Write-Host "[+] HideFastUserSwitching (HKLM)"
} else {
    Write-Warning "Not running as Administrator — HideFastUserSwitching (HKLM) was NOT removed. Re-run as Administrator to remove it."
}

# --- Apply ---
Write-Host "`nRunning gpupdate..." -ForegroundColor Cyan
gpupdate /target:user /force | Out-Null

Write-Host "`nDone. Restart Explorer or log off/on to apply UI changes." -ForegroundColor Green
