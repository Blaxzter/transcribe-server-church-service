<#
  Runs the checks that actually catch problems, fastest-failing first.
  Usage:  .\scripts\verify.ps1
#>
$ErrorActionPreference = "Continue"
$script:failures = @()

function Step {
    param([string]$Name, [scriptblock]$Block)
    Write-Host "`n=== $Name ===" -ForegroundColor Cyan
    try {
        & $Block
        # Native commands signal failure through the exit code, not exceptions.
        if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) {
            throw "exit code $LASTEXITCODE"
        }
    } catch {
        Write-Host "FAILED: $_" -ForegroundColor Red
        $script:failures += $Name
    }
    $global:LASTEXITCODE = 0
}

Step "GPU passthrough into containers" {
    docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 `
        nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader
}

Step "Containers" {
    docker compose ps --format "{{.Service}} -> {{.State}} ({{.Status}})"
}

Step "API health" {
    $health = Invoke-RestMethod http://localhost:8080/api/health -TimeoutSec 10
    Write-Host ($health | ConvertTo-Json -Compress)
}

Step "Worker sees the GPU" {
    docker compose exec -T worker python -c "import torch; print('cuda:', torch.cuda.is_available()); print('device:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'none'); free, total = torch.cuda.mem_get_info() if torch.cuda.is_available() else (0, 0); print(f'vram free {free/1e9:.1f} GB of {total/1e9:.1f} GB')"
}

Step "HF token reaches the worker" {
    $token = docker compose exec -T worker printenv HF_TOKEN
    if ([string]::IsNullOrWhiteSpace($token)) {
        throw "HF_TOKEN is empty - diarization will fail. See README."
    }
    Write-Host "HF_TOKEN present ($($token.Trim().Length) chars)"
}

Step "ffmpeg in the worker" {
    docker compose exec -T worker ffmpeg -version 2>&1 | Select-Object -First 1
}

Step "Logic tests" {
    # These mirror the worker's module-level imports: torch for the music stage,
    # httpx for summarize, fastapi/python-docx for the API's export helpers.
    uv run --no-project --python 3.12 --with pytest --with numpy --with torch `
        --with httpx --with redis --with fastapi --with python-docx python -m pytest tests/
}

Write-Host ""
if ($script:failures.Count -gt 0) {
    Write-Host "FAILED: $($script:failures -join ', ')" -ForegroundColor Red
    exit 1
}
Write-Host "All checks passed." -ForegroundColor Green
