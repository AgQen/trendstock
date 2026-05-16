#!/usr/bin/env pwsh
# 수동 전체 갱신: 가격 -> 등급 -> 검증 -> JSON 굽기 -> git push.
# GitHub Actions cron 과 동일한 흐름. 어디서든 실행 가능 (스크립트 위치 기준 cd).

$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

function Step($label, $cmd) {
    Write-Host ""
    Write-Host "▶ $label" -ForegroundColor Cyan
    & $cmd
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[FAIL] $label" -ForegroundColor Red
        exit 1
    }
}

Step "1/5 가격 수집 (yfinance + pykrx)"       { python -m collectors.run_all }
Step "2/5 룰 기반 등급 재계산"                { python -m collectors.rerate }
Step "3/5 적중률 검증 (7d / 30d / 90d)"      { python -m collectors.verify_predictions }
Step "4/5 web JSON 생성"                     { python -m collectors.export_web }

Write-Host ""
Write-Host "▶ 5/5 git push" -ForegroundColor Cyan
if (-not (Test-Path ".git")) {
    Write-Host "[FAIL] .git 폴더 없음 — GITHUB_SETUP.md 의 B-1 단계 먼저" -ForegroundColor Red
    exit 1
}

$status = git status --porcelain
if (-not $status) {
    Write-Host "  변경 없음 — push 생략"
    Write-Host ""
    Write-Host "[DONE] 분석은 갱신됐지만 푸시할 새 데이터가 없습니다." -ForegroundColor Green
    exit 0
}

$today = Get-Date -Format "yyyy-MM-dd"
git add docs/data/analysis.json data.db 2>$null
git commit -m "refresh $today" | Out-Null
git push

Write-Host ""
Write-Host "[DONE] 30초~1분 후 https://agqen.github.io/trendstock/ 반영" -ForegroundColor Green
