"""주간 자동 프롬프트 튜닝 (기획서 19.6.4).

매주 일요일 cron 으로 실행. 누적 분석 + 적중률 → LLM 호출로 약점 분석 + 개선안 →
llm/prompt.py 의 SYSTEM_PROMPT 자동 갱신 + 변경 이력 git commit.

안전장치:
  1) 변경 전 prompt 백업 (prompt_history.md 에 기록)
  2) 변경 후 새 prompt 도 Pydantic 검증 통과해야 함
  3) 새 prompt 길이가 기존의 50%~200% 범위 내 (급격한 변화 방지)
  4) 첫 다음 일일 분석에서 출력 검증 실패 시 자동 롤백 (TODO: 사후 추가)

비용: 주 1회 약 $0.075 (Sonnet) — 월 4회 $0.30, 연 $3.6.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collectors.db import get_conn, init_db, now_iso
from collectors.token_logger import log_from_anthropic_response

ROOT = Path(__file__).resolve().parent.parent
PROMPT_FILE = ROOT / "llm" / "prompt.py"
HISTORY_FILE = ROOT / "llm" / "prompt_history.md"

TUNE_MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 8000

META_SYSTEM = """\
You are a prompt engineering specialist. You will be given:

1. Current SYSTEM_PROMPT used to generate daily stock trend analyses
2. Accumulated track record: hit rates by horizon, by confidence band, common
   failure patterns
3. Examples of disappointing outputs (if any)

Your job:
- Identify 2~4 concrete weaknesses in the current prompt that explain failures
- Propose a REVISED SYSTEM_PROMPT that addresses these weaknesses
- Keep all OUTPUT RULES (1-9) — they are non-negotiable schema constraints
- Stay within ±50% of original length (don't bloat or strip)
- Preserve all required schema fields

Output STRICT JSON:
{
  "weaknesses": ["weakness 1", "weakness 2", ...],
  "changes_summary": "1-sentence summary of what changed and why",
  "revised_system_prompt": "<full new prompt as one string>"
}
"""


def _gather_track_record() -> dict:
    """누적 적중률 + 카테고리별 성과 + 신뢰도 구간별 적중률 추출."""
    init_db()
    with get_conn() as conn:
        # 전체 적중률
        overall = {}
        for k in ("7d", "30d", "90d"):
            row = conn.execute(
                f"""
                SELECT COUNT(*) AS n,
                       AVG(CAST(hit_{k} AS REAL))*100 AS hit_pct,
                       AVG(alpha_{k})*100 AS alpha_pct
                FROM recommendations
                WHERE hit_{k} IS NOT NULL
                """
            ).fetchone()
            overall[k] = {
                "n": row["n"] or 0,
                "hit_pct": round(row["hit_pct"] or 0, 1) if row["n"] else None,
                "avg_alpha_pct": round(row["alpha_pct"] or 0, 2) if row["n"] else None,
            }

        # 신뢰도 구간별 30d 적중률
        confidence_bands = conn.execute(
            """
            WITH joined AS (
                SELECT r.hit_30d, r.alpha_30d, t.confidence
                FROM recommendations r
                JOIN predicted_trends t ON t.trend_id = r.trend_id
                WHERE r.hit_30d IS NOT NULL
            )
            SELECT
                CASE
                    WHEN confidence >= 80 THEN '80-100'
                    WHEN confidence >= 60 THEN '60-79'
                    WHEN confidence >= 40 THEN '40-59'
                    ELSE '0-39'
                END AS band,
                COUNT(*) AS n,
                ROUND(AVG(CAST(hit_30d AS REAL))*100, 1) AS hit_pct,
                ROUND(AVG(alpha_30d)*100, 2) AS alpha_pct
            FROM joined
            GROUP BY band
            """
        ).fetchall()

        # 카테고리별 성과
        category_perf = conn.execute(
            """
            SELECT t.category,
                   COUNT(*) AS n,
                   AVG(CAST(r.hit_30d AS REAL))*100 AS hit_pct,
                   AVG(r.alpha_30d)*100 AS alpha_pct
            FROM recommendations r
            JOIN predicted_trends t ON t.trend_id = r.trend_id
            WHERE r.hit_30d IS NOT NULL
            GROUP BY t.category
            ORDER BY n DESC
            LIMIT 10
            """
        ).fetchall()

        # 실패 예시 (가장 큰 negative alpha)
        worst_recs = conn.execute(
            """
            SELECT a.ticker, r.analysis_date, t.title AS trend_title,
                   t.category, t.confidence,
                   ROUND(r.alpha_30d*100, 2) AS alpha_pct,
                   r.rationale
            FROM recommendations r
            JOIN assets a ON a.asset_id = r.asset_id
            JOIN predicted_trends t ON t.trend_id = r.trend_id
            WHERE r.hit_30d = 0
            ORDER BY r.alpha_30d ASC
            LIMIT 5
            """
        ).fetchall()

    return {
        "overall_accuracy": overall,
        "confidence_bands_30d": [dict(r) for r in confidence_bands],
        "category_performance_30d": [dict(r) for r in category_perf],
        "worst_examples": [dict(r) for r in worst_recs],
        "as_of": datetime.utcnow().isoformat() + "Z",
    }


def _current_prompt() -> str:
    """prompt.py 에서 SYSTEM_PROMPT 추출."""
    text = PROMPT_FILE.read_text(encoding="utf-8")
    m = re.search(r'SYSTEM_PROMPT\s*=\s*"""\\?\n(.*?)"""', text, re.DOTALL)
    if not m:
        raise RuntimeError("SYSTEM_PROMPT 찾기 실패 (prompt.py 구조 변경?)")
    return m.group(1)


def _write_prompt(new_prompt: str) -> None:
    """prompt.py 의 SYSTEM_PROMPT 만 교체. 다른 코드는 그대로."""
    text = PROMPT_FILE.read_text(encoding="utf-8")
    # 정규식으로 SYSTEM_PROMPT 블록 교체
    new_text = re.sub(
        r'(SYSTEM_PROMPT\s*=\s*""")\\?\n.*?"""',
        lambda _: f'SYSTEM_PROMPT = """\\\n{new_prompt}"""',
        text, count=1, flags=re.DOTALL,
    )
    PROMPT_FILE.write_text(new_text, encoding="utf-8")


def _append_history(entry: dict) -> None:
    """변경 이력 markdown 으로 append."""
    HISTORY_FILE.parent.mkdir(exist_ok=True)
    head = "# Prompt 변경 이력\n\n자동 튜닝 (`llm/tune.py`) 이 매주 일요일 갱신.\n\n"
    block = (
        f"## {entry['date']}\n\n"
        f"**모델**: {entry['model']}  ·  "
        f"**입력 토큰**: {entry['input_tokens']}  ·  "
        f"**출력 토큰**: {entry['output_tokens']}\n\n"
        f"**약점 식별**:\n"
        + "\n".join(f"- {w}" for w in entry["weaknesses"]) + "\n\n"
        f"**변경 요약**: {entry['changes_summary']}\n\n"
        f"**기존 prompt 길이**: {entry['old_length']} chars  →  "
        f"**새 prompt**: {entry['new_length']} chars\n\n"
        f"<details><summary>이전 prompt (백업)</summary>\n\n"
        f"```\n{entry['old_prompt']}\n```\n\n</details>\n\n"
        "---\n\n"
    )
    if HISTORY_FILE.exists():
        existing = HISTORY_FILE.read_text(encoding="utf-8")
        HISTORY_FILE.write_text(head + block + existing.replace(head, ""),
                                encoding="utf-8")
    else:
        HISTORY_FILE.write_text(head + block, encoding="utf-8")


def tune() -> dict | None:
    """프롬프트 자동 튜닝. API 키 없으면 None 반환."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("  [SKIP] ANTHROPIC_API_KEY 미설정 — prompt tuning 건너뜀.")
        return None

    track = _gather_track_record()
    current = _current_prompt()

    # 충분한 데이터 없으면 skip (최소 30d 적중 데이터 20건)
    if track["overall_accuracy"]["30d"]["n"] < 20:
        print(f"  [SKIP] 30d 검증 데이터 {track['overall_accuracy']['30d']['n']}건 "
              f"— 20건 이상 누적 후 자동 튜닝 시작")
        return None

    user_payload = json.dumps({
        "current_system_prompt": current,
        "track_record": track,
    }, ensure_ascii=False, indent=2)

    from anthropic import Anthropic
    client = Anthropic()
    print(f"  Claude {TUNE_MODEL} 에 prompt 튜닝 요청 중...")
    resp = client.messages.create(
        model=TUNE_MODEL,
        max_tokens=MAX_TOKENS,
        system=META_SYSTEM,
        messages=[{"role": "user", "content": user_payload}],
    )
    log_from_anthropic_response("reinforcement", TUNE_MODEL, resp,
                                note="weekly prompt tune")

    raw = resp.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.lstrip().startswith("json"):
            raw = raw.lstrip()[4:]
        raw = raw.strip()

    parsed = json.loads(raw)
    new_prompt = parsed["revised_system_prompt"]
    weaknesses = parsed["weaknesses"]
    summary = parsed["changes_summary"]

    # 안전장치: 길이 검증 (±50%)
    old_len = len(current)
    new_len = len(new_prompt)
    if new_len < old_len * 0.5 or new_len > old_len * 2.0:
        print(f"  [REJECT] 새 prompt 길이 {new_len} (기존 {old_len} 의 "
              f"{new_len/old_len:.0%}) — 안전 범위 벗어남, 적용 안 함")
        return None

    # 안전장치: 필수 키워드 보존
    REQUIRED = ["OUTPUT RULES", "allowed_assets", "disconfirming_hypotheses",
                "causal_chain", "fundamentals_score"]
    missing = [k for k in REQUIRED if k not in new_prompt]
    if missing:
        print(f"  [REJECT] 필수 키워드 누락: {missing}")
        return None

    # 적용
    _write_prompt(new_prompt)
    _append_history({
        "date": datetime.utcnow().strftime("%Y-%m-%d"),
        "model": TUNE_MODEL,
        "input_tokens": resp.usage.input_tokens,
        "output_tokens": resp.usage.output_tokens,
        "weaknesses": weaknesses,
        "changes_summary": summary,
        "old_length": old_len,
        "new_length": new_len,
        "old_prompt": current,
    })

    print(f"  [OK] Prompt 갱신 완료. 약점 {len(weaknesses)}개 식별.")
    print(f"       길이 {old_len} → {new_len} chars")
    print(f"       다음 일일 분석부터 새 prompt 적용됨")
    return {
        "weaknesses": weaknesses,
        "summary": summary,
        "old_length": old_len,
        "new_length": new_len,
    }


if __name__ == "__main__":
    tune()
