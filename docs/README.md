# TrendStock — Web App

개인용 트렌드 주식 분석 PWA. GitHub Pages 로 배포.

**현재 URL** (Pages 활성화 후): `https://agqen.github.io/trendstock/`

## 구조

- `index.html` — 단일 페이지 앱 (CSS + JS 인라인)
- `manifest.json` — PWA 매니페스트
- `sw.js` — Service Worker (오프라인 캐시)
- `icon.svg` — 아이콘
- `data/analysis.json` — 매일 갱신되는 분석 데이터 (앱 폴더의 `collectors.export_web` 가 생성)

## 매일 배포

상위 `app/` 폴더에서:

```powershell
python -m collectors.run_all          # 가격 수집
python -m collectors.rerate            # 등급 재계산 (선택)
python -m collectors.verify_predictions # 적중률 갱신
python -m collectors.export_web        # docs/data/analysis.json 갱신
.\refresh.ps1                          # git push -> Pages 자동 갱신 (~30초)
```
