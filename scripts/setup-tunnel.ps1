<#
.SYNOPSIS
  Adds an ingress rule for the transcription server to the running Cloudflare Tunnel.

.DESCRIPTION
  MUST BE RUN AS ADMINISTRATOR.

  The tunnel on this machine is locally managed and runs as a Windows service
  under LocalSystem, which reads its config from the systemprofile directory -
  NOT the copy in your user profile. Editing the user-profile copy does nothing.

  This script edits the live config, inserting the new hostname above the
  catch-all rule, then restarts the service. Existing rules (including the SSH
  one) are left untouched.

.EXAMPLE
  .\scripts\setup-tunnel.ps1
#>
#Requires -RunAsAdministrator
[CmdletBinding()]
param(
    [string]$HostName   = "freddy-transcribe.fabraham.dev",
    [string]$Service    = "http://localhost:8080",
    [string]$ConfigPath = "C:\Windows\System32\config\systemprofile\.cloudflared\config.yml"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $ConfigPath)) {
    throw "Tunnel config not found at $ConfigPath. Find the live path with: Get-CimInstance Win32_Service -Filter ""Name='Cloudflared'"" | Select-Object PathName"
}

$lines = Get-Content $ConfigPath
Write-Host "Current config:`n" -ForegroundColor Cyan
$lines | ForEach-Object { "  $_" }

if ($lines -match [regex]::Escape($HostName)) {
    Write-Host "`n$HostName is already in the config - nothing to do." -ForegroundColor Yellow
    exit 0
}

# Back up before touching anything.
$backup = "$ConfigPath.bak-$(Get-Date -Format yyyyMMdd-HHmmss)"
Copy-Item $ConfigPath $backup
Write-Host "`nBacked up to $backup" -ForegroundColor DarkGray

# The catch-all (`- service: http_status:404`) must stay last, so insert above it.
$catchAll = $lines | Select-String -Pattern '^\s*-\s*service:\s*http_status:' | Select-Object -First 1
if (-not $catchAll) {
    throw "Could not find the 'http_status' catch-all rule; edit $ConfigPath by hand."
}
$index  = $catchAll.LineNumber - 1
$indent = ($lines[$index] -replace '^(\s*).*', '$1')

$newRule = @(
    "$indent- hostname: $HostName"
    "$indent  service: $Service"
    "$indent  originRequest:"
    "$indent    connectTimeout: 30s"
    "$indent    # Long uploads and the SSE progress stream both need generous"
    "$indent    # timeouts; SSE must not be buffered."
    "$indent    noTLSVerify: false"
)

$updated = @()
$updated += $lines[0..($index - 1)]
$updated += $newRule
$updated += $lines[$index..($lines.Count - 1)]
Set-Content -Path $ConfigPath -Value $updated -Encoding UTF8

Write-Host "`nNew config:`n" -ForegroundColor Cyan
Get-Content $ConfigPath | ForEach-Object { "  $_" }

Write-Host "`nValidating..." -ForegroundColor Cyan
# `ingress validate` is a subcommand of `tunnel`; the top-level form silently
# falls through to the tunnel help and exits non-zero.
& "C:\Program Files (x86)\cloudflared\cloudflared.exe" --config $ConfigPath tunnel ingress validate
if ($LASTEXITCODE -ne 0) {
    Copy-Item $backup $ConfigPath -Force
    throw "Config failed validation; restored the backup. Nothing was changed."
}

Write-Host "`nRestarting the Cloudflared service..." -ForegroundColor Cyan
Restart-Service Cloudflared
Start-Sleep -Seconds 5
Get-Service Cloudflared | Format-Table Name, Status, StartType -AutoSize

Write-Host "`nDone. Next: run scripts\setup-access.ps1 to put Cloudflare Access in front of it." -ForegroundColor Green
Write-Host "Until Access is configured, $HostName is PUBLIC. Do not share the URL yet." -ForegroundColor Yellow
