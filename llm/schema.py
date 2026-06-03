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
    stock_desc: str | None = None         # 회사가 하는 일, 포지션 (2~3문장)
    trend_link: str | None = None         # 이 트렌드에서 왜 이 종목이 파생됐는지
    current_flow: str | None = None       # 현재 주가·거래량·모멘텀 흐름
    financials_reason: str | None = None  # 재무점수 산출 근거 (주요 지표 언급)
    prediction: str | None = None         # 상승/하락 예측 근거 (predicted에 필수)


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
    timeframe: Literal["ongoing", "imminent", "short", "medium"] | None = None
    confidence: int = Field(ge=0, le=100)
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


class DailyAnalysis(BaseModel):
    analysis_date: str  # 'YYYY-MM-DD'
    model_name: str
    current_trends: list[TrendCard] = Field(min_length=1, max_length=5)
    predicted_trends: list[TrendCard] = Field(min_length=1, max_length=5)

    @field_validator("current_trends", "predicted_trends")
    @classmethod
    def sector_diversity(cls, v: list[TrendCard]) -> list[TrendCard]:
        """5개 트렌드는 최소 4개 카테고리 커버 (편향 방지, 19.3.5 #1)."""
        if len(v) >= 4:
            cats = {t.category for t in v}
            if len(cats) < min(4, len(v)):
                raise ValueError(
                    f"섹터 다양성 부족: {len(v)}개 트렌드인데 "
                    f"카테고리 {len(cats)}개 ({cats})"
                )
        return v
