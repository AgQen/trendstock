# Prompt 변경 이력

자동 튜닝 (`llm/tune.py`) 이 매주 일요일 갱신.

조건:
- 30d 적중 데이터 20건 이상 누적
- 새 prompt 길이가 기존의 50~200% 범위 내
- 필수 키워드(OUTPUT RULES, allowed_assets, disconfirming_hypotheses, causal_chain, fundamentals_score) 보존

위 조건 미충족 시 자동 skip — prompt 그대로 유지.

---

## 초기 (2026-05-15)

수동 작성. 기획서 19.3.1 의 OUTPUT RULES 9개 + 인과 추론 + 섹터 다양성 + 추천 형식.

자동 튜닝은 데이터 누적 (예상 6월 중) 후 첫 작동 예정.
