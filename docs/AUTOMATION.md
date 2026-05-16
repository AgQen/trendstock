# 자동화 운영 가이드

매일 KST 06:50 에 GitHub Actions cron 이 자동 갱신을 실행. 본 문서는 **무엇이 어떻게 작동하는지** + **시나리오별 동작** + **확인/모니터링** + **문제 발생 시** 정리.

> 셋업 절차는 [SETUP_AUTO.md](../SETUP_AUTO.md) 참조. 본 문서는 셋업 끝난 후 운영 관점.

---

## 1. 매일 무슨 일이 일어나나

`.github/workflows/daily-refresh.yml` 가 매일 자동 실행 (KST 06:50, UTC 21:50 전일):

```
06:50 KST  cron 발동
  │
  ├─ 1. yfinance / pykrx 로 어제 종가 수집 (모든 140 종목)
  ├─ 2. 적중률 검증 — 7d/30d/90d 도래한 예측 알파 계산
  ├─ 3. LLM 분석 — Claude 호출 → 새 트렌드 5+5 + 추천 ~30 건 생성
  ├─ 4. 룰 기반 객관 등급 적용 — LLM 주관 등급을 펀더+모멘텀+타이밍 룰로 덮어쓰기
  ├─ 5. docs/data/analysis.json 새로 굽기
  └─ 6. git commit + push
  │
07:00 KST  GitHub Pages 빌드 완료, 폰에서 새로고침하면 새 분석
```

평균 소요 시간 약 **2~3 분**.

---

## 2. 시나리오별 동작

LLM 호출의 성공 여부에 따라 자동으로 다르게 동작:

| 상황 | LLM step | 매일 일어나는 일 | 폰 화면 |
|---|---|---|---|
| 🟢 **API 키 등록 + 잔액 있음** | 정상 실행 | 새 트렌드/추천 생성 + 룰 등급 + 적중률 모두 갱신 | 매일 새 분석 |
| 🟡 **API 키 미등록** | graceful skip | LLM 분석은 어제 그대로. **단 가격/등급/적중률은 갱신** | 분석 날짜 어제 그대로, 등급/적중률은 갱신 |
| 🟠 **API 키 등록 + 잔액 0** | LLM step 실패하나 `continue-on-error: true` 라 무시 | 위와 동일 (LLM 분석 어제, 나머지 갱신) | 동일 |
| 🔴 **API 키 잘못됨** | LLM step 실패하나 무시 | 위와 동일 | 동일 |

**핵심**: 어떤 상황에서도 **가격 / 룰 등급 / 적중률 갱신은 멈추지 않음**. LLM 만 부가적으로 더해짐.

---

## 3. 어디서 확인하나

### 3.1 폰에서 (가장 자주)

```
https://agqen.github.io/trendstock/
```

- 상단 **분석일** 이 어제 → 오늘 로 갱신됐는지
- 좌측 사이드바 → **💰 토큰 사용** 카드에 어제 호출 비용 누적됐는지
- **🕓 히스토리** 에 어제 새 행이 추가됐는지

### 3.2 GitHub Actions 탭 (cron 정상 동작 확인)

```
https://github.com/AgQen/trendstock/actions
```

- 매일 새벽 1 회 실행 기록 보임
- ✅ 초록 = 모든 step 성공
- 🟡 노랑 = 일부 step 무시 (continue-on-error)
- ❌ 빨강 = 핵심 step 실패 — 클릭해서 로그 확인

### 3.3 Anthropic Console (API 비용)

```
https://console.anthropic.com/usage
```

- 일별/월별 토큰 사용량 + 누적 비용
- 잔액 상태

---

## 4. 직접 트리거 (즉시 갱신)

자동 cron 이 다음 새벽이라 즉시 갱신이 필요할 때.

### 4.1 GitHub 웹에서 (PC 안 켜둬도 됨)

1. https://github.com/AgQen/trendstock/actions
2. 좌측 **Daily TrendStock Refresh** 클릭
3. 우측 **Run workflow** 버튼 → main → **Run workflow**
4. 2~3 분 후 폰 새로고침

### 4.2 PC 로컬에서 (디버깅 / 빠른 반복)

```powershell
cd "C:\Users\ok\OneDrive\바탕 화면\code\클로드\Trade inf App\트랜드 주식 앱\app"
.\refresh.ps1
```

→ cron 과 동일한 6 단계 흐름. 30 초~1 분.

---

## 5. 트러블슈팅

### 5.1 Actions 가 빨갛게 (❌) 떴을 때

1. https://github.com/AgQen/trendstock/actions 접속
2. 실패한 workflow 클릭
3. 빨간 X 가 붙은 step 클릭
4. 로그 확인

**자주 보는 에러**:

| 에러 메시지 | 원인 | 해결 |
|---|---|---|
| `BadRequestError: credit balance too low` | Anthropic 잔액 0 | Console 에서 충전 |
| `anthropic.AuthenticationError` | API 키 잘못됨 | Secrets 재등록 (SETUP_AUTO.md 2-2) |
| `ModuleNotFoundError: collectors` | app/ 전체가 repo 에 없음 | `git push -f` 로 app 전체 다시 |
| `Permission denied: git push` | workflow 권한 누락 | yml 의 `permissions: contents: write` 확인 |
| `yfinance.exceptions.YFRateLimitError` | yfinance 일시 차단 | 1~2 시간 후 자동 회복 |

### 5.2 폰에서 새 데이터가 안 보일 때

1. **Service Worker 캐시**: 브라우저에서 강력 새로고침. PWA 면 앱 닫고 다시 열기 (2 회)
2. **GitHub Pages 빌드 지연**: 보통 push 후 30 초~2 분. 5 분 지나도 안 보이면 https://github.com/AgQen/trendstock/actions 에서 `pages-build-deployment` workflow 확인
3. **시크릿 탭 테스트**: 시크릿 탭으로 같은 URL 열어보기. 시크릿에선 보이면 일반 탭 캐시 문제

### 5.3 LLM 분석이 매일 안 생성될 때

체크리스트 순서:

- [ ] Anthropic Console 잔액 > $0?
- [ ] GitHub Secrets 에 `ANTHROPIC_API_KEY` 정확히 등록?
- [ ] Actions 의 LLM step 로그에 에러 메시지?
- [ ] 같은 키를 PowerShell `python -m llm.run` 로 로컬 실행 시 작동?

---

## 6. 비용 관리

### 6.1 모니터링 위치

| 위치 | 무엇 |
|---|---|
| 앱 좌측 사이드바 (💰 토큰 사용) | 최근 30 일 누적 (DB 자체 기록) |
| Anthropic Console / Usage | 실시간 정확한 사용량 |
| Anthropic Console / Plans & Billing | 잔액 |

### 6.2 폭증 방지

Anthropic Console 에서:
- **Usage limits** → 월 한도 설정 (예 $5) → 초과 시 자동 차단
- **알람** → 잔액 $1 미만 시 이메일

### 6.3 토큰 절감

[COSTS.md](COSTS.md) 6 항목 참조. `llm/optimize.py` 의 3 가지 절감 옵션 활성화 시 최대 80% 절감.

---

## 7. 정기 점검 (월 1 회 권장)

| 항목 | 어디서 | 무엇을 |
|---|---|---|
| Anthropic 잔액 | console.anthropic.com | $1 미만이면 충전 |
| 적중률 통계 | 앱 사이드바 | 30 일 적중률 50% 이상? |
| Actions 성공률 | Actions 탭 | 최근 30 실행 중 ❌ 몇 개? |
| 토큰 비용 | 사이드바 또는 Console | 예상 수준 (₩3,000/월) 내인지 |

---

## 8. 그만 두고 싶을 때

자동화 멈춤 — 데이터/코드 보존하고 cron 만 중단:

1. https://github.com/AgQen/trendstock/actions
2. 좌측 **Daily TrendStock Refresh** 클릭
3. 우측 **⋯** 메뉴 → **Disable workflow**

→ 매일 자동 실행 중단. 데이터는 GitHub Pages 에 그대로 남음. 언제든 다시 Enable 가능.

완전 폐기:
1. 모든 데이터 export — 앱에서 Excel 다운로드 1 회
2. https://console.anthropic.com 에서 API 키 삭제
3. (선택) https://github.com/AgQen/trendstock/settings → Delete this repository

---

## 9. 한 줄 요약

> **API 키 등록 + Actions 활성화 → 매일 새벽 자동 갱신. PC 안 켜도 됨. 폰 즐겨찾기로 확인. 가격/룰/적중률은 LLM 없어도 계속 돌아감.**
