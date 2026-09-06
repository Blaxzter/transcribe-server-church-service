<#
.SYNOPSIS
  Puts Cloudflare Access (one-time PIN) in front of the transcription server.

.DESCRIPTION
  Creates a self-hosted Access application for the hostname and an allow policy
  limited to the listed email addresses. Everyone else gets bounced at
  Cloudflare's edge, before a request ever reaches this machine.

  Your API token is never written to disk or echoed. Pass it as a parameter or
  set CLOUDFLARE_API_TOKEN in the shell you run this from.

  The token needs these permissions (My Profile -> API Tokens -> Create Token
  -> Custom token):
      Account | Access: Apps and Policies | Edit
      Account | Account Settings          | Read
      Zone    | Zone                      | Read

  Re-running is safe: an existing application for the same hostname is reused
  and its policy updated rather than duplicated.

.EXAMPLE
  .\scripts\setup-access.ps1 -ApiToken "..." -Emails "you@example.com","her@example.com"

.EXAMPLE
  $env:CLOUDFLARE_API_TOKEN = "..."
  .\scripts\setup-access.ps1 -Emails "you@example.com"
#>
[CmdletBinding()]
param(
    [string]$ApiToken = $env:CLOUDFLARE_API_TOKEN,
    [Parameter(Mandatory)][string[]]$Emails,
    [string]$HostName = "freddy-transcribe.fabraham.dev",
    [string]$AppName  = "Transkript",
    # One month - the single biggest usability lever for a non-technical user.
    # With one-time PIN this is the difference between fetching a code from your
    # inbox every visit and doing it roughly once a month. It also guarantees a
    # 90-minute upload can never be interrupted by a re-auth redirect.
    # The trade-off is that a signed-in browser stays signed in for a month,
    # which is the right call on someone's own laptop.
    [string]$SessionDuration = "730h"
)

$ErrorActionPreference = "Stop"
$api = "https://api.cloudflare.com/client/v4"

if ([string]::IsNullOrWhiteSpace($ApiToken)) {
    throw "No API token. Pass -ApiToken or set CLOUDFLARE_API_TOKEN. See the help in this file for the permissions it needs."
}
$headers = @{ Authorization = "Bearer $ApiToken"; "Content-Type" = "application/json" }

function Invoke-CF {
    param([string]$Method, [string]$Path, $Body)
    $args = @{ Method = $Method; Uri = "$api$Path"; Headers = $headers }
    if ($Body) { $args.Body = ($Body | ConvertTo-Json -Depth 12 -Compress) }
    try {
        return Invoke-RestMethod @args
    } catch {
        # Cloudflare puts the useful part in the response body, not the status line.
        $detail = ""
        if ($_.ErrorDetails.Message) { $detail = $_.ErrorDetails.Message }
        elseif ($_.Exception.Response) {
            $reader = New-Object IO.StreamReader($_.Exception.Response.GetResponseStream())
            $detail = $reader.ReadToEnd()
        }
        throw "$Method $Path failed: $($_.Exception.Message)`n$detail"
    }
}

# --- 1. token + account -----------------------------------------------------
Write-Host "Verifying token..." -ForegroundColor Cyan
$verify = Invoke-CF GET "/user/tokens/verify"
if (-not $verify.success) { throw "Token verification failed." }
Write-Host "  token status: $($verify.result.status)" -ForegroundColor Green

$zoneName = ($HostName -split '\.' | Select-Object -Last 2) -join '.'
Write-Host "Looking up zone $zoneName..." -ForegroundColor Cyan
$zones = Invoke-CF GET "/zones?name=$zoneName"
if (-not $zones.result -or $zones.result.Count -eq 0) {
    throw "Zone $zoneName not found. Does the token have Zone:Read for it?"
}
$accountId = $zones.result[0].account.id
Write-Host "  account: $($zones.result[0].account.name) ($accountId)" -ForegroundColor Green

# --- 2. application ---------------------------------------------------------
Write-Host "Checking for an existing Access application..." -ForegroundColor Cyan
$existing = (Invoke-CF GET "/accounts/$accountId/access/apps").result |
    Where-Object { $_.domain -eq $HostName } | Select-Object -First 1

if ($existing) {
    $appId = $existing.id
    Write-Host "  reusing existing application ($appId)" -ForegroundColor Yellow
} else {
    $appBody = @{
        name                      = $AppName
        domain                    = $HostName
        type                      = "self_hosted"
        session_duration          = $SessionDuration
        auto_redirect_to_identity = $false
        app_launcher_visible      = $true
        # Empty = every configured login method, which includes the built-in
        # one-time PIN. That is what we want: no IdP to set up.
        allowed_idps              = @()
    }
    $app = Invoke-CF POST "/accounts/$accountId/access/apps" $appBody
    $appId = $app.result.id
    Write-Host "  created application ($appId)" -ForegroundColor Green
}

# --- 3. policy --------------------------------------------------------------
# Cloudflare moved to reusable account-level policies; older accounts still
# expose the app-scoped endpoint. Try the modern shape, fall back to the legacy
# one, so this works either way.
$include = @($Emails | ForEach-Object { @{ email = @{ email = $_ } } })
$policyBody = @{
    name     = "$AppName - erlaubte Personen"
    decision = "allow"
    include  = $include
}

$policyId = $null
try {
    Write-Host "Creating reusable policy..." -ForegroundColor Cyan
    $policy = Invoke-CF POST "/accounts/$accountId/access/policies" $policyBody
    $policyId = $policy.result.id
    Write-Host "  policy $policyId" -ForegroundColor Green

    Write-Host "Attaching policy to the application..." -ForegroundColor Cyan
    Invoke-CF PUT "/accounts/$accountId/access/apps/$appId" @{
        name             = $AppName
        domain           = $HostName
        type             = "self_hosted"
        session_duration = $SessionDuration
        policies         = @(@{ id = $policyId; precedence = 1 })
    } | Out-Null
    Write-Host "  attached" -ForegroundColor Green
} catch {
    Write-Host "  reusable-policy path failed, trying the app-scoped endpoint" -ForegroundColor Yellow
    Write-Verbose $_
    $policyBody.precedence = 1
    $legacy = Invoke-CF POST "/accounts/$accountId/access/apps/$appId/policies" $policyBody
    $policyId = $legacy.result.id
    Write-Host "  policy $policyId (app-scoped)" -ForegroundColor Green
}

# --- 4. verify --------------------------------------------------------------
Write-Host "`nVerifying..." -ForegroundColor Cyan
$final = Invoke-CF GET "/accounts/$accountId/access/apps/$appId"
Write-Host "  name:     $($final.result.name)"
Write-Host "  domain:   $($final.result.domain)"
Write-Host "  session:  $($final.result.session_duration)"
Write-Host "  allowed:  $($Emails -join ', ')"

Write-Host "`nDone. https://$HostName is now behind Cloudflare Access." -ForegroundColor Green
Write-Host "Confirm it works from a private window: you should get a one-time-PIN prompt," -ForegroundColor Green
Write-Host "and an email NOT on the list should be refused." -ForegroundColor Green
