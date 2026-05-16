# TrendStock V1 — app

W1 단계 산출물. 데이터 수집 → SQLite 저장 파이프라인.

## 실행

```powershell
cd app
pip install -r requirements.txt
python -m collectors.run_all      # 시드 + 미국/한국 주식 수집
python -m collectors.query        # 저장 결과 점검
```

## 구조

```
app/
├── data.db                # SQLite (런타임에 자동 생성)
├── db/schema.sql          # 테이블 정의
├── seeds/assets.json      # 추적 대상 종목 마스터
└── collectors/
    ├── db.py              # 연결/스키마/로그 헬퍼
    ├── seed_assets.py     # assets.json → assets 테이블 upsert
    ├── collect_us.py      # yfinance: 미국 종목 30일치 OHLCV
    ├── collect_kr.py      # pykrx: 한국 종목 30일치 OHLCV
    ├── run_all.py         # init + seed + 미국 + 한국 일괄 실행
    └── query.py           # 저장 결과 sanity check
```

## 다음 단계 (W2)

- FRED / NewsAPI / DART 수집 추가 (API 키 발급 필요)
- 트렌드 탐지 + LLM 분석 파이프라인 (ANTHROPIC_API_KEY 필요)
- analysis_history 테이블 + 적중률 cron
