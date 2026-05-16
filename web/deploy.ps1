#!/usr/bin/env pwsh
# Daily push to GitHub Pages.
# 실행 위치 무관 (스크립트 자기 위치 기준 cd).

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

if (-not (Test-Path ".git")) {
    Write-Host "[FAIL] .git 폴더 없음 — 먼저 'git init' + remote 설정 필요" -ForegroundColor Red
    exit 1
}

# data/analysis.json 변동 있는지 체크
$status = git status --porcelain
if (-not $status) {
    Write-Host "[INFO] 변경된 파일 없음 — 푸시 생략"
    exit 0
}

$today = Get-Date -Format "yyyy-MM-dd"
$msg = "update $today"

Write-Host "[STEP] git add ."
git add .

Write-Host "[STEP] git commit -m `"$msg`""
git commit -m $msg

Write-Host "[STEP] git push"
git push

Write-Host "[OK] 배포 완료. 30초~1분 후 https://agqen.github.io/trendstock/ 반영"
