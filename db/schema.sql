-- TrendStock V1 — W1 SQLite schema
-- Postgres 호환을 위해 SQLite 전용 문법(AUTOINCREMENT 외)은 사용 안 함.

CREATE TABLE IF NOT EXISTS assets (
    asset_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker      TEXT NOT NULL,
    name        TEXT NOT NULL,
    exchange    TEXT NOT NULL,
    country     TEXT NOT NULL,        -- 'US' | 'KR' | ...
    asset_class TEXT NOT NULL DEFAULT 'stock',
    industry    TEXT,
    sector      TEXT,
    currency    TEXT NOT NULL,        -- 'USD' | 'KRW' | ...
    is_active   INTEGER NOT NULL DEFAULT 1,
    UNIQUE (ticker, exchange)
);

CREATE INDEX IF NOT EXISTS idx_assets_country ON assets(country);
CREATE INDEX IF NOT EXISTS idx_assets_active  ON assets(is_active);

CREATE TABLE IF NOT EXISTS price_history (
    asset_id INTEGER NOT NULL REFERENCES assets(asset_id),
    date     TEXT    NOT NULL,        -- 'YYYY-MM-DD'
    open     REAL,
    high     REAL,
    low      REAL,
    close    REAL,
    volume   REAL,
    PRIMARY KEY (asset_id, date)
);

CREATE INDEX IF NOT EXISTS idx_price_date ON price_history(date DESC);

CREATE TABLE IF NOT EXISTS collection_log (
    log_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    source       TEXT NOT NULL,
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    rows_added   INTEGER DEFAULT 0,
    rows_updated INTEGER DEFAULT 0,
    error        TEXT
);

-- ===================================================================
-- S1: 분석 결과 영속화 + 적중률 검증 (기획서 19.6)
-- ===================================================================

-- 매일 1건. UNIQUE(analysis_date)로 중복 방지.
CREATE TABLE IF NOT EXISTS analysis_snapshots (
    snapshot_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_date   TEXT NOT NULL UNIQUE,
    model_name      TEXT,                  -- 'claude-sonnet-4-6' | 'manual-by-claude-code' | ...
    raw_json        TEXT NOT NULL,         -- 전체 분석 결과 원본
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_snapshots_date ON analysis_snapshots(analysis_date DESC);

-- 트렌드 카드 (현재 트렌드 + 예측 트렌드).
CREATE TABLE IF NOT EXISTS predicted_trends (
    trend_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id         INTEGER NOT NULL REFERENCES analysis_snapshots(snapshot_id),
    analysis_date       TEXT NOT NULL,
    kind                TEXT NOT NULL,      -- 'current' | 'predicted'
    rank                INTEGER NOT NULL,   -- 트렌드 내 우선순위 (1..N)
    title               TEXT NOT NULL,
    summary             TEXT,
    category            TEXT,               -- 'AI 메모리', 'GLP-1', '한국 콘텐츠', ...
    timeframe           TEXT,               -- 'ongoing' | 'imminent' | 'short' | 'medium'
    confidence          INTEGER,            -- 0~100
    causal_chain_json   TEXT,               -- [{step_no, statement, confidence}, ...]
    disconfirming_json  TEXT,               -- ["반대 가설1", "반대 가설2", ...]
    evidence_json       TEXT                -- 가격/거래량/뉴스 근거 묶음
);

CREATE INDEX IF NOT EXISTS idx_trends_date ON predicted_trends(analysis_date DESC);
CREATE INDEX IF NOT EXISTS idx_trends_snapshot ON predicted_trends(snapshot_id);

-- 트렌드별 추천 종목 + 진입 시점 기록 (검증의 기준선).
CREATE TABLE IF NOT EXISTS recommendations (
    rec_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    trend_id            INTEGER NOT NULL REFERENCES predicted_trends(trend_id),
    snapshot_id         INTEGER NOT NULL REFERENCES analysis_snapshots(snapshot_id),
    analysis_date       TEXT NOT NULL,
    asset_id            INTEGER NOT NULL REFERENCES assets(asset_id),
    rank                INTEGER,
    grade               TEXT,               -- 'Strong Buy' | 'Buy' | 'Hold' | 'Caution'
    rationale           TEXT,               -- 왜 추천인가 (한 문장)
    entry_close         REAL NOT NULL,      -- 진입 시점 종가 (검증의 기준)
    fundamentals_score  INTEGER,            -- 0~9
    fundamentals_json   TEXT,               -- 그날 펀더 스냅샷 (재무 지표 묶음)
    -- 검증 결과 (verify_predictions.py 가 채움)
    close_7d            REAL,
    close_30d           REAL,
    close_90d           REAL,
    bench_7d            REAL,
    bench_30d           REAL,
    bench_90d           REAL,
    alpha_7d            REAL,               -- (close_7d/entry - 1) - (bench_7d/entry_bench - 1)
    alpha_30d           REAL,
    alpha_90d           REAL,
    hit_7d              INTEGER,            -- 1=알파>0, 0=알파<=0, NULL=미검증
    hit_30d             INTEGER,
    hit_90d             INTEGER,
    verified_at         TEXT,
    -- 룰 기반 객관 등급 (ratings.py)
    rating_score        INTEGER,            -- -4 ~ +6
    rating_breakdown_json TEXT,              -- {fundamentals, momentum, timing 각 score+reasons}
    -- LLM 생성 상세 설명 (RecDetail)
    detail_json         TEXT                -- {stock_desc, trend_link, current_flow, financials_reason, prediction}
);

CREATE INDEX IF NOT EXISTS idx_rec_date ON recommendations(analysis_date DESC);
CREATE INDEX IF NOT EXISTS idx_rec_asset ON recommendations(asset_id);
CREATE INDEX IF NOT EXISTS idx_rec_trend ON recommendations(trend_id);
CREATE INDEX IF NOT EXISTS idx_rec_verify ON recommendations(analysis_date, verified_at);

-- 검증 cron 실행 로그.
CREATE TABLE IF NOT EXISTS verification_log (
    log_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date        TEXT NOT NULL,
    verified_count  INTEGER,
    horizons_json   TEXT,                   -- {"7d":N, "30d":N, "90d":N}
    error           TEXT,
    created_at      TEXT NOT NULL
);

-- LLM API 토큰 사용 기록.
-- category: 'daily_analysis' | 'reinforcement' | 'app_interaction' | 'retro_report'
CREATE TABLE IF NOT EXISTS token_usage (
    usage_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    date            TEXT NOT NULL,          -- 'YYYY-MM-DD' (KST 기준)
    category        TEXT NOT NULL,
    model           TEXT NOT NULL,          -- 'claude-sonnet-4-6' 등
    input_tokens    INTEGER NOT NULL DEFAULT 0,
    cached_input_tokens INTEGER NOT NULL DEFAULT 0,  -- prompt caching 시 read 토큰
    output_tokens   INTEGER NOT NULL DEFAULT 0,
    cost_usd        REAL NOT NULL DEFAULT 0,
    note            TEXT,
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_token_date ON token_usage(date DESC);
CREATE INDEX IF NOT EXISTS idx_token_cat  ON token_usage(category);

-- 룰 기반 점수 가중치 이력.
-- effective_date 최신 행이 현재 활성 가중치.
CREATE TABLE IF NOT EXISTS rule_weights (
    weight_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    effective_date  TEXT NOT NULL UNIQUE,
    fund_weight     REAL NOT NULL DEFAULT 0.9,
    momentum_weight REAL NOT NULL DEFAULT 0.6,
    timing_weight   REAL NOT NULL DEFAULT 1.0,
    volume_weight   REAL NOT NULL DEFAULT 1.0,
    rs_weight       REAL NOT NULL DEFAULT 1.2,   -- 상대강도 (SPY 대비 초과수익)
    risk_weight     REAL NOT NULL DEFAULT 0.8,   -- 위험도/MDD
    note            TEXT,
    created_at      TEXT NOT NULL
);
