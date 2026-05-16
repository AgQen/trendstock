# 옵션 B — 매일 자동 갱신 셋업

GitHub Actions cron + Anthropic API 로 매일 KST 06:50 에 자동 새 분석 생성/배포.

PC 안 켜둬도 됨. 1회 셋업 후 잊고 살면 됨.

---

## 0. 사전 조건 (이미 완료)

- ✅ `AgQen/trendstock` repo 에 app 전체 push 됨
- ✅ GitHub Pages folder = `/docs` 로 설정됨
- ✅ `.github/workflows/daily-refresh.yml` workflow 파일 존재

---

## 1. Anthropic API 키 발급 (5분, $5)

### 1-1. Console 가입

브라우저로:
```
https://console.anthropic.com
```

Google/이메일로 가입 (이미 Pro 구독 중이라면 같은 이메일 사용 가능 — 단 API 결제는 별개).

### 1-2. 결제 정보 등록 + $5 충전

좌측 메뉴:
- **Plans & Billing** 클릭
- **Add credit** 또는 **Buy credits** 클릭
- 카드 등록 후 **$5** 충전

> $5 면 Sonnet 4.6 기준 약 2~3 개월 운영 가능 (월 약 3,000 원).

### 1-3. API 키 발급

좌측 메뉴:
- **API Keys** 클릭
- **Create Key** 클릭
- 이름: `trendstock-cron` (구분 용도)
- 생성된 키 `sk-ant-xxxxx...` **메모장에 복사** (한 번만 표시됨)

---

## 2. GitHub Secrets 등록 (2분)

GitHub 가 cron 실행할 때 API 키를 안전하게 가져오도록 등록.

### 2-1. Repo Settings → Secrets

브라우저로:
```
https://github.com/AgQen/trendstock/settings/secrets/actions
```

### 2-2. 새 Secret 추가

- **New repository secret** 클릭
- **Name**: `ANTHROPIC_API_KEY` (대소문자 정확히)
- **Value**: 위 1-3 에서 복사한 `sk-ant-xxxxx...` 붙여넣기
- **Add secret** 클릭

→ 키는 GitHub 에 암호화 저장됨. workflow 실행 시에만 환경변수로 주입됨. push log 나 commit 에는 노출 안 됨.

---

## 3. Workflow 활성화 + 첫 수동 테스트 (5분)

### 3-1. Actions 탭

브라우저로:
```
https://github.com/AgQen/trendstock/actions
```

처음 들어가면 *"Workflows aren't being run on this repository"* 가 뜰 수 있음.
**I understand my workflows, go ahead and enable them** 클릭.

### 3-2. Daily TrendStock Refresh 수동 트리거

좌측 **Daily TrendStock Refresh** 클릭 → 우측 **Run workflow** 버튼 → **main** branch 선택 → **Run workflow**.

→ 1~3분 후 ✅ 또는 ❌ 결과 확인.

### 3-3. 결과 확인

| 결과 | 의미 | 다음 |
|---|---|---|
| ✅ 초록 체크 | 수집 + 분석 + push 모두 성공 | https://agqen.github.io/trendstock/ 새로고침 → 새 데이터 확인 |
| ❌ 빨간 X | 어딘가 실패 | 클릭 → 빨간 step 로그 → 에러 메시지 확인 |

---

## 4. 매일 자동 실행 확인

이후 매일 KST 06:50 (UTC 21:50 전일) 에 자동 실행.

### 어떻게 확인하나?

매일 아침 폰에서 `https://agqen.github.io/trendstock/` 열어보면:
- 상단 분석일 이 어제 → 오늘 로 갱신됨
- 좌측 사이드바 **💰 토큰 사용** 카드에 호출/비용 누적됨

또는:
```
https://github.com/AgQen/trendstock/actions
```
→ 최근 workflow 실행 기록 확인.

---

## 5. 비용 관리

### 모니터링 위치

- 좌측 사이드바 토큰 카드 (최근 30 일 누적)
- https://console.anthropic.com/usage (Anthropic 공식)

### 예상 비용

| 모델 | 월 비용 | 비고 |
|---|---|---|
| Sonnet 4.6 (default) | 약 ₩3,000 | 균형 |
| Haiku 4.5 (저렴) | 약 ₩1,000 | 품질 한 단계 낮음 |
| Opus 4.7 (최고) | 약 ₩15,000 | 분석 품질 최고 |

기본은 Sonnet. `llm/run.py` 의 `DEFAULT_MODEL` 상수 변경으로 전환.

### 비용 폭증 방지

`llm/optimize.py` 의 토큰 절감 옵션:
- **Prompt caching**: System prompt 자동 캐싱 → 입력 토큰 50~70% 절감
- **2단계 라우팅**: Haiku 1차 필터 → Sonnet 2차 심층
- **컨텍스트 압축**: 변동 큰 종목만 LLM 에 전달

활성화 방법은 `llm/optimize.py` 주석 참조. Day-2 데이터 누적 후 적용 권장.

---

## 6. 트러블슈팅

### Q. Workflow 가 빨간 X (실패)

Actions 페이지에서 실패한 workflow 클릭 → 빨간 step 클릭하면 로그 보임.

**자주 보는 에러**:

| 에러 | 원인 | 해결 |
|---|---|---|
| `anthropic.AuthenticationError` | API 키 잘못됨 | 2-2 다시 (값 정확한지 확인) |
| `BadRequestError: credit balance too low` | $5 소진 | 1-2 다시 충전 |
| `ModuleNotFoundError: collectors` | app/ 전체가 repo 에 없음 | 옵션 B-1 (force push) 재확인 |
| Push permission denied | workflow 의 `permissions: contents: write` 누락 | `.github/workflows/daily-refresh.yml` 확인 |

### Q. 분석은 됐는데 폰에 반영 안 됨

- Service Worker 가 옛 캐시 보여줄 수 있음
- 폰 브라우저에서 **강력 새로고침** (보통 새로고침 1~2번)
- 또는 PWA 닫고 다시 열기

### Q. LLM 분석을 잠시 중단하고 싶음

- Anthropic Console → API Keys → 키 옆 휴지통 (Disable)
- 다시 활성화: 새 키 발급 → GitHub Secrets 갱신
- 또는 그냥 결제 안 함 (잔액 0 되면 자동 skip — workflow 는 룰 기반 갱신만 계속됨)

---

## 7. 옵션 A 와 함께 사용

자동 cron 활성화 후에도 PC 에서 수동 실행 가능 — 즉시 갱신하고 싶을 때:

```powershell
cd "C:\Users\ok\OneDrive\바탕 화면\code\클로드\Trade inf App\트랜드 주식 앱\app"
.\refresh.ps1
```

→ 30초~1분 후 같은 결과. 두 방식은 충돌 안 함.

---

**완료**. 다음 새벽부터 매일 자동으로 새 분석이 생성/배포됩니다. 폰에서 매일 아침 확인만 하시면 됩니다.
