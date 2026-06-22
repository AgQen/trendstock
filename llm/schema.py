"""LLM 출력 검증용 Pydantic 모델 (기획서 19.3.1).

save_analysis.py 가 받는 JSON 과 동일한 구조.
LLM 응답을 이 모델로 model_validate 한 뒤, model_dump() 결과를 save_analysis.save() 에 전달.
"""

from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field, field_validator


class CausalStep(BaseModel):
    step_no: int = Field(ge=1)
    statement: str = Field(min_length=5)
    confidence: int = Field(ge=0, le=100)


class Fundamentals(BaseModel):
    """그날 시점 펀더 스냅샷 (지표 모두 선택)."""
    revenue_yoy_pct: float | None = None
    operating_margin_pct: float | None = None
    net_margin_pct: float | None = None
    roe_pct: float | None = None
    pe_ratio: float | None = None
    ps_ratio: float | None = None
    debt_to_equity: float | None = None
    market_cap_usd_b: float | None = None
    fcf_usd_b: float | None = None


class RecDetail(BaseModel):
    """추천 종목 상세 설명 (expandable 섹션용)."""
    stock_desc: str | None = None               # 회사가 하는 일, 포지션 (2~3문장)
    trend_link: str | None = None               # 이 트렌드에서 왜 이 종목이 파생됐는지
    current_flow: str | None = None             # 현재 주가·거래량·모멘텀 흐름 (1d/5d/20d %)
    financials_reason: str | None = None        # 현재 시점 재무점수 근거 (주요 지표)
    financials_trajectory: str | None = None    # 과거→현재 재무 변화 (예: OPM 32%→67% +35%p)
    momentum_direction: str | None = None       # "상승" | "하락" | "횡보" + 근거 한 줄
    prediction: str | None = None               # 상승/하락 예측 근거 (predicted에 필수)


class Recommendation(BaseModel):
    rank: int = Field(ge=1)
    ticker: str = Field(min_length=1)
    grade: Literal["Strong Buy", "Buy", "Hold", "Caution"]
    rationale: str = Field(min_length=5)   # 한 줄 요약
    fundamentals_score: int = Field(ge=0, le=9)
    fundamentals: Fundamentals = Field(default_factory=Fundamentals)
    detail: RecDetail | None = None        # 상세 설명 (선택, 있으면 UI 확장 표시)


class TrendCard(BaseModel):
    rank: int = Field(ge=1)
    title: str = Field(min_length=3)
    summary: str
    category: str
    timeframe: str | None = None  # ongoing/imminent/short/medium — 자유 텍스트 허용
    confidence: int = Field(ge=0, le=100)
    # v3 트렌드 엔진 점수 (predicted_trends에 직접 포함 — 별도 매칭 불필요)
    trend_score: float | None = Field(default=None, ge=0, le=100)
    trend_direction: Literal["UP", "DOWN"] | None = None
    secondary_effect: str | None = None   # 2차 파급 효과
    trend_risk: str | None = None         # 틀릴 수 있는 변수
    causal_chain: list[CausalStep] = Field(min_length=1)
    disconfirming_hypotheses: list[str] = Field(min_length=1)
    evidence: dict = Field(default_factory=dict)
    # 트렌드당 1~3개 — 정말 확신 있는 것만 (Strong Buy 또는 고신뢰 Buy)
    recommendations: list[Recommendation] = Field(min_length=1, max_length=3)

    @field_validator("causal_chain")
    @classmethod
    def chain_confidence_monotone(cls, v: list[CausalStep]) -> list[CausalStep]:
        """단계 진행할수록 신뢰도가 떨어져야 함 (강한 가정은 못 함)."""
        for i in range(1, len(v)):
            if v[i].confidence > v[i - 1].confidence + 5:
                raise ValueError(
                    f"causal_chain step {v[i].step_no} confidence "
                    f"{v[i].confidence} > prev {v[i-1].confidence}+5"
                )
        return v


# ──────────────────────────────────────────────────────
# AI Investment Trend Engine v3 — 시장 브리프 모델
# ──────────────────────────────────────────────────────

class DetectedEvent(BaseModel):
    event: str
    impact: Literal["약함", "보통", "강함", "매우 강함"]
    source_type: str   # 공식/주요언론/일반언론/소셜/시장가격 등 — 자유 텍스트 허용
    time_weight: float = Field(ge=0.0, le=1.5)
    reason: str


class TrendCandidate(BaseModel):
    rank: int = Field(ge=1)
    theme: str
    score: float = Field(ge=0, le=100)
    direction: Literal["UP", "DOWN"]
    representative_stocks: list[str] = Field(min_length=1)  # 추천 종목 티커와 1:1 정렬
    reason: str
    secondary_effect: str
    risk: str


class RelatedCandidate(BaseModel):
    theme: str
    score: float = Field(ge=0, le=100)
    short_reason: str


class ExcludedCandidate(BaseModel):
    theme: str
    reason: str


class MarketBrief(BaseModel):
    """AI Investment Trend Engine v3 출력 — 시장 국면 + 트렌드 후보 분석."""
    news_summary: str
    market_context: str
    detected_events: list[DetectedEvent] = Field(default_factory=list)
    top_trend_candidates: list[TrendCandidate] = Field(min_length=2, max_length=6)
    related_candidates: list[RelatedCandidate] = Field(default_factory=list, max_length=5)
    excluded_or_weak_candidates: list[ExcludedCandidate] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class DailyAnalysis(BaseModel):
    analysis_date: str  # 'YYYY-MM-DD'
    model_name: str
    market_brief: MarketBrief         # v3 트렌드 분석 (필수)
    current_trends: list[TrendCard] = Field(min_length=1, max_length=5)
    predicted_trends: list[TrendCard] = Field(min_length=2, max_length=5)  # 최소 2개

    @field_validator("current_trends", "predicted_trends")
    @classmethod
    def sector_diversity(cls, v: list[TrendCard]) -> list[TrendCard]:
        if len(v) >= 4:
            cats = {t.category for t in v}
            if len(cats) < min(4, len(v)):
                raise ValueError(
                    f"섹터 다양성 부족: {len(v)}개 트렌드인데 "
                    f"카테고리 {len(cats)}개 ({cats})"
                )
        return v

    @field_validator("predicted_trends")
    @classmethod
    def predicted_must_have_score(cls, v: list[TrendCard]) -> list[TrendCard]:
        """예측 트렌드는 반드시 v3 점수(trend_score, trend_direction)를 포함해야 함."""
        for t in v:
            if t.trend_score is None:
                raise ValueError(
                    f"predicted_trend '{t.title}' is missing trend_score. "
                    "Each predicted_trend MUST include trend_score (0-100) and trend_direction."
                )
            if t.trend_direction is None:
                raise ValueError(
                    f"predicted_trend '{t.title}' is missing trend_direction (UP/DOWN)."
                )
        return v
