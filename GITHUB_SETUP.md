# GitHub Actions 자동 갱신 셋업

매일 KST 06:50 에 자동으로 가격 수집 + 등급 갱신 + 적중률 검증 + GitHub Pages 배포.

---

## 사전 상태 (현재)

- ✅ `AgQen/trendstock` repo 에 `web/` 폴더 내용만 push 되어 있음
- ✅ GitHub Pages 가 `https://agqen.github.io/trendstock/` 에서 서빙 중
- ⏳ Cron 자동화는 아래 셋업 후 활성화

---

## 옵션 A — 단순 (현재 구조 유지, 수동 갱신)

PC 에서 매일 1줄 실행:

```powershell
cd "C:\Users\ok\OneDrive\바탕 화면\code\클로드\Trade inf App\트랜드 주식 앱\app"
python -m collectors.run_all
python -m collectors.rerate
python -m collectors.verify_predictions
python -m collectors.export_web
.\web\deploy.ps1
```

→ 30초 ~ 1분. Pages 반영까지 추가 1분.

---

## 옵션 B — 자동 (GitHub Actions cron)

매일 KST 06:50 자동 실행 — PC 꺼져있어도 동작.

### B-1. app 전체를 GitHub repo 로 push

현재는 `web/` 만 git 관리. `app/` 전체를 한 repo 로 묶어야 cron 이 `collectors/`, `db/`, `llm/` 모듈을 실행 가능.

**현재 web/ 만의 repo 를 app/ 전체로 확장**:

```powershell
# 1. app/ 폴더 자체에 git init
cd "C:\Users\ok\OneDrive\바탕 화면\code\클로드\Trade inf App\트랜드 주식 앱\app"
git init -b main

# 2. 기존 web/ 의 .git 폴더는 충돌하니 제거 (web 폴더 안의 파일은 유지)
Remove-Item -Recurse -Force web\.git

# 3. .gitignore 추가 (이미 web/.gitignore 있지만 app/ 레벨로 확장)
@"
__pycache__/
*.pyc
.venv/
*.db-journal
_check_*.py
_fill_*.py
_extra_*.py
"@ | Out-File -FilePath .gitignore -Encoding utf8 -Append

# 4. 모두 stage + commit
git add .
git commit -m "initial: TrendStock full app (collectors + web + workflows)"

# 5. 같은 GitHub repo 에 push (기존 web-only 커밋은 force-overwrite)
git remote add origin https://github.com/AgQen/trendstock.git
git push -f origin main
```

> **주의**: `git push -f` 는 기존 repo 내용을 덮어씁니다. `web/` 만 있던 상태는 사라지지만 모든 파일이 다시 올라가므로 결과적으로 같음.

### B-2. GitHub Pages 설정 변경

기존엔 `main / (root)` 였는데, 이제 `web/` 이 서브폴더이므로 변경:

1. https://github.com/AgQen/trendstock/settings/pages
2. **Branch**: `main`
3. **Folder**: `/web` ← 이전엔 `/ (root)` 였음
4. **Save**

→ Pages URL 은 동일 (`https://agqen.github.io/trendstock/`).

### B-3. (선택) Anthropic API 키 등록

LLM 분석까지 자동화하려면:

1. https://github.com/AgQen/trendstock/settings/secrets/actions
2. **New repository secret** 클릭
3. **Name**: `ANTHROPIC_API_KEY`
4. **Value**: `sk-ant-...` (Console 에서 발급)
5. **Add secret**

→ 다음 cron 실행부터 LLM 호출 포함. 토큰 자동 기록 + 사이드바 표시.

키 없으면 룰 기반만 갱신 (workflow 가 자동으로 skip).

### B-4. workflow 활성화 확인

1. https://github.com/AgQen/trendstock/actions
2. 좌측 **Daily TrendStock Refresh** 클릭
3. 우측 **Run workflow** 버튼 → 즉시 실행 테스트
4. 초록 ✓ 뜨면 성공. 매일 KST 06:50 자동 실행됨.

---

## 빠른 트러블슈팅

| 증상 | 원인 | 해결 |
|---|---|---|
| Action 빨간 ❌ | Python 모듈 누락 | workflow 의 `pip install` 줄 확인 |
| `ModuleNotFoundError: collectors` | `app/` 전체가 push 안 됨 | B-1 단계 다시 |
| Pages 404 | folder 설정 안 바꿈 | B-2 단계 다시 |
| LLM 분석 skip | API 키 미등록 | B-3 단계 (선택) |
| Push permission denied | `permissions: contents: write` 누락 | workflow 파일 확인 |
