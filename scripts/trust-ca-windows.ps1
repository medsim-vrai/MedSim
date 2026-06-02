<#
.SYNOPSIS
  Trust the MedSim dev root CA on THIS Windows host so Chrome/Edge stop warning
  about the local HTTPS cert. Windows twin of scripts/trust-ca-mac.sh.

.DESCRIPTION
  The cert, key, chain and SAN are already correct (generate them with
  `python scripts/dev_cert.py`). The ONLY missing piece is the *trust* setting:
  a root CA can sit in the store UNtrusted, which is exactly the "Not Secure"
  state. This installs the CA into the LocalMachine Trusted Root store, which is
  what Chrome/Edge on Windows evaluate.

  Trusting a root CA is a system-security change, so this must be Run as
  Administrator. Idempotent: clears any stale "MedSim Dev Local CA" entries
  (old re-mints) from the store first, then installs the CURRENT rootCA.pem.

.EXAMPLE
  # In an elevated PowerShell (Run as Administrator):
  pwsh -File scripts/trust-ca-windows.ps1
  # or Windows PowerShell 5.1:
  powershell -ExecutionPolicy Bypass -File scripts\trust-ca-windows.ps1

.NOTES
  Validate on the first real Windows host (this repo's CI/dev is macOS).
#>
[CmdletBinding()]
param(
  [string]$CaPath = (Join-Path $PSScriptRoot '..\portal\data\certs\rootCA.pem')
)
$ErrorActionPreference = 'Stop'
$CaCn = 'MedSim Dev Local CA'

# --- guards -----------------------------------------------------------------
if (-not $IsWindows -and $env:OS -ne 'Windows_NT') {
  Write-Error 'This script is Windows-only. On macOS use scripts/trust-ca-mac.sh.'
  exit 1
}
$CaPath = (Resolve-Path -LiteralPath $CaPath -ErrorAction SilentlyContinue)
if (-not $CaPath -or -not (Test-Path -LiteralPath $CaPath)) {
  Write-Error "No CA found. Run `python scripts/dev_cert.py` first to generate portal/data/certs/rootCA.pem."
  exit 1
}
$isAdmin = ([Security.Principal.WindowsPrincipal] `
  [Security.Principal.WindowsIdentity]::GetCurrent()
  ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
  Write-Error 'Trusting a root CA is a system-security change and needs admin. Re-run this in an elevated (Run as Administrator) PowerShell.'
  exit 1
}

# --- fingerprint (SHA-256, to match dev_cert.py / cert-doctor) --------------
$cert = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2($CaPath)
$sha = [System.Security.Cryptography.SHA256]::Create()
$fpr = (($sha.ComputeHash($cert.RawData)) | ForEach-Object { $_.ToString('X2') }) -join ':'
Write-Host "Trusting root CA on this Windows host:"
Write-Host "  file:    $CaPath"
Write-Host "  SHA-256: $fpr`n"

# 1. Remove stale copies (old re-mints) so trust can't latch onto a duplicate.
Get-ChildItem Cert:\LocalMachine\Root |
  Where-Object { $_.Subject -match [regex]::Escape($CaCn) } |
  ForEach-Object {
    Write-Host "  removing stale CA: $($_.Thumbprint)"
    Remove-Item -LiteralPath ("Cert:\LocalMachine\Root\" + $_.Thumbprint) -Force
  }

# 2. Install + TRUST the current CA as a root in the machine store.
Import-Certificate -FilePath $CaPath -CertStoreLocation Cert:\LocalMachine\Root | Out-Null

Write-Host "`n[OK] CA installed and trusted as a root (LocalMachine\Root)."
Write-Host "  NEXT: fully quit Chrome/Edge and reopen it — it caches trust at launch."
Write-Host "  Verify: python scripts\dev_cert.py doctor"
Write-Host "          Get-ChildItem Cert:\LocalMachine\Root | ? Subject -match 'MedSim Dev Local CA'"
