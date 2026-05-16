"""yfinance 기반 펀더멘털 조회.

미국: 정식 티커 (NVDA, MSFT, ...)
한국: .KS 접미사 (005930.KS = 삼성전자), .KQ 접미사 (KOSDAQ).
한국 데이터는 일부 필드 누락 빈번 — 정확도 한계 있음. 정식 펀더는 DART 도입 시 보강.
"""

import sys
import yfinance as yf


# 큐레이팅된 한 줄 설명 (yfinance 영문 요약보다 우선 사용).
# 새 종목 분석 시 여기에 한 줄 추가하면 됨.
DESCRIPTIONS: dict[str, str] = {
    # ── 미국 반도체 ──
    "NVDA":  "AI GPU 사실상 독점. 데이터센터·게이밍·자동차 칩 1위.",
    "AMD":   "CPU/GPU 2위. AI 가속기(MI300)로 NVDA 추격 중.",
    "INTC":  "PC/서버 CPU 전통강자. 파운드리 진출 중이나 적자 지속.",
    "TSM":   "세계 1위 파운드리. 애플·NVDA·AMD 칩 위탁생산 독점.",
    "ASML":  "EUV 노광장비 세계 유일. 첨단 반도체 공정 필수 설비.",
    "AVGO":  "네트워크/AI ASIC 칩 + VMware. 구글 TPU 협력사.",
    "MU":    "메모리 3사(D램·낸드). 마이크론. HBM3E NVDA 인증 통과.",
    "QCOM":  "모바일 AP 1위(스냅드래곤). 자동차·IoT로 확장 중.",
    "ARM":   "모바일 CPU 설계 IP. 애플·퀄컴이 라이선스 받는 회사.",
    "SMCI":  "AI 서버 ODM. NVDA GPU 탑재 서버 제조 점유율 급증.",

    # ── 미국 빅테크/소프트웨어 ──
    "MSFT":  "Windows/Office + Azure 클라우드 2위. OpenAI 최대 투자자.",
    "AAPL":  "아이폰·맥·서비스. 세계 시총 1~2위 다툼.",
    "GOOGL": "구글 검색·유튜브·광고 + Gemini AI + 클라우드 3위.",
    "META":  "페이스북·인스타·왓츠앱·스레드. AI 광고 효율 1위.",
    "AMZN":  "이커머스 + AWS 클라우드 1위 + 광고 사업 급성장.",
    "TSLA":  "전기차 1위 + 자율주행 + 에너지저장. 머스크.",
    "ORCL":  "DB 1위 + 클라우드 인프라(OCI) 후발. AI 학습 클라우드 성장.",
    "CRM":   "세계 1위 CRM 소프트웨어(Salesforce). AI 에이전트 사업 확장.",
    "PLTR":  "정부/국방 AI 데이터 분석 플랫폼. AIP로 민간 확장.",
    "NOW":   "기업 IT 워크플로우 자동화 1위(ServiceNow). AI 통합.",

    # ── 미국 전력/유틸리티/원자력 ──
    "CCJ":   "캐나다 우라늄 채굴 1위(Cameco). 원전 르네상스 직접 수혜.",
    "VST":   "미국 전력 발전사. AI 데이터센터 전력 공급 계약 폭증.",
    "GEV":   "GE 분사 신재생/원전/가스터빈. 전력 인프라 종합.",
    "NRG":   "미국 전력/소매 에너지. AI 데이터센터 PPA 계약 확대.",

    # ── 미국 금융/기타 ──
    "JPM":   "미국 1위 종합은행. 시총 기준 글로벌 은행 1위.",
    "BAC":   "미국 2위 종합은행(뱅크오브아메리카).",
    "GS":    "투자은행 1위(골드만삭스). M&A·IPO 자문.",
    "COIN":  "미국 1위 암호화폐 거래소. 비트코인 시세에 직접 연동.",
    "MSTR":  "마이크로스트래티지. 비트코인 최대 보유 상장사(약 60만개).",
    "UBER":  "글로벌 라이드셰어 1위 + 음식배달(Uber Eats).",

    # ── 미국 반도체 장비/소프트웨어 ──
    "AMAT":  "어플라이드 머티리얼즈. 반도체 식각·CVD·이온주입 장비 1위.",
    "KLAC":  "KLA. 반도체 결함 검사 장비 절대 강자. 미세공정 필수.",
    "LRCX":  "램리서치. 식각·증착 장비 빅3 중 하나. 메모리 비중 큼.",
    "MRVL":  "마벨. 데이터센터 커스텀 ASIC + 광통신 칩.",
    "ANET":  "아리스타. AI 데이터센터 고속 스위치 1위(메타·MS 주력).",
    "CDNS":  "케이던스. 반도체 설계 EDA 툴 빅2. SNPS와 양분.",
    "SNPS":  "시놉시스. 반도체 설계 EDA 툴 1위.",

    # ── 미국 소프트웨어/IT ──
    "ADBE":  "어도비. 포토샵·일러스트·PDF 독점. 디자인 SaaS 1위.",
    "INTU":  "인튜이트. TurboTax(세금) + QuickBooks(중소기업 회계) 1위.",
    "IBM":   "IBM. 하이브리드 클라우드(Red Hat) + AI(왓슨X) + 컨설팅.",
    "NFLX":  "넷플릭스. 글로벌 1위 스트리밍. 광고요금제 + 게임 확장.",
    "DIS":   "월트디즈니. IP·디즈니플러스·테마파크·ESPN.",
    "CRWD":  "크라우드스트라이크. 엔드포인트 보안(클라우드) 1위.",
    "PANW":  "팰로앨토. 네트워크 보안 + 클라우드 보안 종합.",
    "SNOW":  "스노우플레이크. 클라우드 데이터 웨어하우스 1위 독립 벤더.",
    "DDOG":  "데이터독. 클라우드 인프라 모니터링 1위.",

    # ── 미국 통신/미디어 ──
    "T":     "AT&T. 미국 무선통신 3사 중 하나 + 광인터넷.",
    "VZ":    "버라이즌. 미국 무선통신 1위 (시장점유율).",
    "TMUS":  "T모바일. 5G 1위 + 가입자 순증가 1위.",
    "CMCSA": "컴캐스트. 미국 케이블 1위 + NBC유니버설(피콕 스트리밍).",

    # ── 미국 유틸리티 (AI 전력 수혜 후보) ──
    "NEE":   "넥스트에라. 미국 최대 재생에너지 발전사 + 플로리다 전력.",
    "DUK":   "듀크에너지. 미국 동남부 전력 독점 공기업급 유틸리티.",
    "SO":    "서던컴퍼니. 미국 남부 전력 + 신규 원전(보글) 운영.",

    # ── 미국 금융 추가 ──
    "WFC":   "웰스파고. 미국 4대 은행 + 모기지 강자.",
    "C":     "씨티그룹. 글로벌 IB + 신용카드.",
    "MS":    "모건스탠리. 자산관리 + IB 글로벌 강자.",
    "V":     "비자. 글로벌 결제망 1위(가맹점 망 사실상 독점).",
    "MA":    "마스터카드. 글로벌 결제망 2위. 비자와 양분.",
    "AXP":   "아메리칸익스프레스. 프리미엄 신용카드 + 자체 결제망.",
    "BLK":   "블랙록. 세계 1위 자산운용사(약 $10조 운용).",
    "SCHW":  "찰스슈왑. 미국 1위 디스카운트 브로커리지.",
    "SPGI":  "S&P 글로벌. 신용평가 + 지수(S&P500) + 데이터.",
    "BRK-B": "버크셔 해서웨이. 워런 버핏 그룹. 보험·철도·에너지·주식.",

    # ── 미국 헬스케어/제약 (GLP-1 사이클) ──
    "UNH":   "유나이티드헬스. 미국 1위 건강보험 + Optum(헬스서비스).",
    "JNJ":   "존슨앤존슨. 제약 + 의료기기 + 컨슈머. 글로벌 종합.",
    "LLY":   "일라이릴리. **GLP-1(젭바운드/마운자로) 핵심**. 비만치료제 1위.",
    "PFE":   "화이자. 코로나 백신 후폭풍 + 항암 라인업 회복 중.",
    "ABBV":  "애브비. 휴미라 후속(스카이리지·린버크) + 보톡스(앨러간).",
    "MRK":   "머크. 키트루다(면역항암) 글로벌 매출 1위 의약품.",
    "TMO":   "써모피셔. 생명과학 연구장비/시약 1위.",
    "ISRG":  "인튜이티브 서지컬. 수술 로봇(다빈치) 독점.",
    "AMGN":  "암젠. 바이오테크 대형주 + 신규 비만치료제(마리타이드) 후보.",
    "GILD":  "길리어드. HIV·간염 치료제 + 항암 확대 중.",
    "VRTX":  "버텍스. 낭포성섬유증 독점 + 비오피오이드 진통제 신규.",
    "NVO":   "노보 노디스크. **GLP-1(오젬픽/위고비) 원조**. 비만치료 양강.",

    # ── 미국 소비재 ──
    "WMT":   "월마트. 미국 1위 종합 유통 + 이커머스(아마존 추격).",
    "COST":  "코스트코. 회원제 창고형 마트 + 고객 충성도 절대적.",
    "PG":    "P&G. 생활용품 글로벌 1위(타이드·팸퍼스·질레트).",
    "KO":    "코카콜라. 글로벌 음료 1위. 버핏 장기 보유.",
    "PEP":   "펩시코. 음료 + 스낵(프리토레이) 통합 글로벌 강자.",
    "MCD":   "맥도날드. 글로벌 1위 패스트푸드. 부동산 사업 모델.",
    "HD":    "홈디포. 미국 1위 홈센터(DIY).",
    "LOW":   "로우스. 미국 2위 홈센터.",
    "NKE":   "나이키. 글로벌 1위 스포츠 의류·신발.",
    "SBUX":  "스타벅스. 글로벌 1위 커피 체인.",
    "BKNG":  "부킹홀딩스. Booking.com·프라이스라인. 호텔 OTA 1위.",

    # ── 미국 에너지 ──
    "XOM":   "엑손모빌. 미국 최대 석유 메이저(통합 정유사).",
    "CVX":   "셰브론. 미국 2위 석유 메이저.",
    "COP":   "코노코필립스. 미국 최대 E&P(탐사·생산) 전문.",
    "SLB":   "슬럼버제. 글로벌 1위 유전 서비스(오일필드 서비스).",

    # ── 미국 산업/방산 ──
    "CAT":   "캐터필러. 글로벌 1위 건설·광산 중장비.",
    "DE":    "디어. 글로벌 1위 농기계(존디어).",
    "HON":   "하니웰. 항공·산업자동화·빌딩솔루션 다각화.",
    "GE":    "GE 에어로스페이스. 항공기 엔진(보잉·에어버스 공급).",
    "BA":    "보잉. 미국 항공기 제조 (737/787/777). 방산도 큰 비중.",
    "RTX":   "RTX(레이시온). 미국 방산 빅3 + 항공기 엔진(P&W).",
    "LMT":   "록히드마틴. 미국 방산 1위(F-35 전투기).",

    # ── 미국 소재 ──
    "LIN":   "린데. 글로벌 1위 산업가스(반도체·헬스케어 공급).",
    "NEM":   "뉴몬트. 세계 1위 금광 채굴.",
    "FCX":   "프리포트맥모란. 세계 1위 구리 광산 + 금/몰리브덴.",

    # ── 미국 REIT ──
    "AMT":   "아메리칸타워. 글로벌 1위 통신 타워 REIT.",
    "EQIX":  "에퀴닉스. 글로벌 1위 데이터센터 REIT.",

    # ── 미국 ETF/벤치마크 ──
    "SPY":   "[ETF] S&P 500 추종. 미국 대형주 종합 벤치마크.",
    "QQQ":   "[ETF] NASDAQ 100 추종. 미국 기술주 중심.",
    "XLK":   "[ETF] S&P 500 IT 섹터.",
    "XLF":   "[ETF] S&P 500 금융 섹터.",
    "XLE":   "[ETF] S&P 500 에너지 섹터.",
    "XLV":   "[ETF] S&P 500 헬스케어 섹터.",
    "SMH":   "[ETF] VanEck 반도체. 반도체 섹터 집중 ETF.",

    # ── 한국 벤치마크 ──
    "069500.KS": "[ETF] KODEX 200. KOSPI 200 추종 (한국 대형주 벤치마크).",

    # ── 한국 ──
    "005930.KS": "삼성전자. 메모리/파운드리/스마트폰/가전. HBM3E 양산 시작.",
    "000660.KS": "SK하이닉스. HBM 글로벌 점유율 1위. NVDA 최대 공급사.",
    "042700.KS": "한미반도체. HBM 후공정 본더 장비 사실상 독점.",
    "035420.KS": "NAVER. 한국 1위 검색·이커머스·웹툰·AI(하이퍼클로바).",
    "035720.KS": "카카오. 메신저·금융·콘텐츠·모빌리티 그룹 지주.",
    "005380.KS": "현대차. 글로벌 3위 완성차. 하이브리드·EV·수소차.",
    "000270.KS": "기아. 현대차 그룹. SUV·하이브리드 글로벌 호조.",
    "051910.KS": "LG화학. 석유화학 + 양극재(LG에너지솔루션 모회사).",
    "006400.KS": "삼성SDI. 전기차 배터리 + ESS. 유럽·미국 OEM 공급.",
    "247540.KQ": "에코프로비엠. 양극재 점유율 글로벌 상위.",
    "086520.KQ": "에코프로. 에코프로비엠 모회사. 양극재 수직계열화.",
    "207940.KS": "삼성바이오로직스. 글로벌 1위 바이오 위탁생산(CDMO).",
    "068270.KS": "셀트리온. 바이오시밀러 글로벌 선두(램시마·트룩시마).",
    "105560.KS": "KB금융지주. 국민은행 모회사.",
    "055550.KS": "신한지주. 신한은행 모회사.",
    "086790.KS": "하나금융지주. 하나은행 모회사.",
    "316140.KS": "우리금융지주. 우리은행 모회사.",
    "035900.KQ": "JYP Ent. 트와이스·스트레이키즈·있지 소속사.",
    "041510.KQ": "에스엠. NCT·에스파·라이즈 소속사. 카카오 자회사.",
    "352820.KS": "하이브. BTS·뉴진스·세븐틴·르세라핌 소속 종합 엔터.",
    "047810.KS": "한국항공우주(KAI). FA-50 전투기·헬기. 폴란드 수출 호조.",
    "064350.KS": "현대로템. K2 전차. 폴란드 1·2차 계약 수혜.",
    "010140.KS": "삼성중공업. LNG선·해양플랜트 글로벌 상위 조선소.",
    "042660.KS": "한화오션(구 대우조선해양). LNG선·잠수함.",
    "015760.KS": "한국전력. 한국 전력 독점 공기업. 요금 인상이 핵심 변수.",
    "003550.KS": "LG. LG그룹 지주사 (전자·화학·생활건강 등).",
    "028260.KS": "삼성물산. 삼성그룹 사실상 지주사 + 건설·상사·패션.",
    "011200.KS": "HMM(옛 현대상선). 한국 1위 컨테이너 해운.",
    "097950.KS": "CJ제일제당. 식품(비비고)·바이오·사료. K-푸드 글로벌.",
    "035250.KS": "강원랜드. 한국 유일 내국인 출입 카지노.",
}


def short_desc(ticker: str, info: dict) -> str:
    """큐레이팅 사전 우선, 없으면 yfinance 요약 첫 문장."""
    if ticker in DESCRIPTIONS:
        return DESCRIPTIONS[ticker]
    summary = info.get("longBusinessSummary") or ""
    if summary:
        first = summary.split(". ")[0]
        return first[:200] + ("..." if len(first) > 200 else "")
    return ""


def fetch(ticker: str) -> dict:
    info = yf.Ticker(ticker).info or {}
    return info


def pct(v):
    if v is None:
        return None
    return v * 100


def grade(info: dict) -> tuple[str, list[str]]:
    """초간단 점수 (만점 9). 신호 사유 함께 반환."""
    score = 0
    reasons: list[str] = []

    rev_growth = info.get("revenueGrowth") or 0
    op_margin  = info.get("operatingMargins") or 0
    np_margin  = info.get("profitMargins") or 0
    roe        = info.get("returnOnEquity") or 0
    d_to_e     = info.get("debtToEquity") or 0
    pe         = info.get("trailingPE") or 0
    fcf        = info.get("freeCashflow") or 0

    if rev_growth >= 0.20:
        score += 2; reasons.append(f"매출 YoY +{rev_growth*100:.0f}% (강함)")
    elif rev_growth >= 0.10:
        score += 1; reasons.append(f"매출 YoY +{rev_growth*100:.0f}% (양호)")
    elif rev_growth > 0:
        reasons.append(f"매출 YoY +{rev_growth*100:.0f}% (둔화)")
    elif rev_growth < 0:
        score -= 1; reasons.append(f"매출 YoY {rev_growth*100:.0f}% (감소)")

    if op_margin >= 0.25:
        score += 2; reasons.append(f"영업이익률 {op_margin*100:.0f}% (탁월)")
    elif op_margin >= 0.15:
        score += 1; reasons.append(f"영업이익률 {op_margin*100:.0f}% (양호)")
    elif op_margin > 0:
        reasons.append(f"영업이익률 {op_margin*100:.0f}% (보통)")

    if roe >= 0.20:
        score += 2; reasons.append(f"ROE {roe*100:.0f}% (강함)")
    elif roe >= 0.10:
        score += 1; reasons.append(f"ROE {roe*100:.0f}%")

    if 0 < d_to_e < 50:
        score += 1; reasons.append(f"부채비율 낮음 ({d_to_e:.0f})")
    elif d_to_e >= 200:
        score -= 1; reasons.append(f"부채비율 과다 ({d_to_e:.0f})")

    if 0 < pe < 25:
        score += 1; reasons.append(f"P/E {pe:.0f} (합리)")
    elif 25 <= pe < 40:
        reasons.append(f"P/E {pe:.0f} (다소 부담)")
    elif pe >= 40:
        score -= 1; reasons.append(f"P/E {pe:.0f} (고평가)")

    if fcf and fcf > 0:
        score += 1; reasons.append(f"잉여현금흐름 +${fcf/1e9:.1f}B")

    # 9점 만점 매핑
    if score >= 7:
        verdict = "Strong Buy"
    elif score >= 5:
        verdict = "Buy"
    elif score >= 3:
        verdict = "Hold"
    else:
        verdict = "Caution"
    return verdict, reasons


def report(ticker: str, label: str | None = None) -> None:
    try:
        info = fetch(ticker)
    except Exception as e:
        print(f"  [FAIL] {ticker} {type(e).__name__}: {e}")
        return

    name = info.get("shortName") or info.get("longName") or ticker
    if label:
        print(f"\n── {ticker}  ({label})  ─ {name}")
    else:
        print(f"\n── {ticker}  ─ {name}")

    desc = short_desc(ticker, info)
    if desc:
        print(f"   ▸ {desc}")

    mcap = info.get("marketCap") or 0
    print(f"   시총       : ${mcap/1e9:>8.1f}B" if mcap else "   시총       : n/a")
    rg = pct(info.get("revenueGrowth"))
    print(f"   매출 YoY   : {rg:>+7.1f}%" if rg is not None else "   매출 YoY   : n/a")
    om = pct(info.get("operatingMargins"))
    print(f"   영업이익률 : {om:>+7.1f}%" if om is not None else "   영업이익률 : n/a")
    pm = pct(info.get("profitMargins"))
    print(f"   순이익률   : {pm:>+7.1f}%" if pm is not None else "   순이익률   : n/a")
    roe = pct(info.get("returnOnEquity"))
    print(f"   ROE        : {roe:>+7.1f}%" if roe is not None else "   ROE        : n/a")
    pe = info.get("trailingPE")
    print(f"   P/E (TTM)  : {pe:>7.1f}" if pe else "   P/E (TTM)  : n/a")
    ps = info.get("priceToSalesTrailing12Months")
    print(f"   P/S        : {ps:>7.1f}" if ps else "   P/S        : n/a")
    de = info.get("debtToEquity")
    print(f"   부채/자본  : {de:>7.0f}" if de else "   부채/자본  : n/a")
    cash = info.get("totalCash") or 0
    print(f"   현금       : ${cash/1e9:>8.1f}B" if cash else "   현금       : n/a")
    fcf = info.get("freeCashflow") or 0
    print(f"   FCF        : ${fcf/1e9:>+8.1f}B" if fcf else "   FCF        : n/a")

    verdict, reasons = grade(info)
    print(f"   ─────────────────────────────")
    print(f"   ▶ 등급 : {verdict}")
    print(f"   ▶ 근거 : {' · '.join(reasons[:5]) if reasons else '데이터 부족'}")


def main() -> None:
    # 데모 대상: 현재 트렌드 대장 + 다음 트렌드 후보
    targets = [
        # === 현재 키워드: AI 메모리 슈퍼사이클 ===
        ("NVDA",       "현재트렌드 · AI GPU + HBM 수요처"),
        ("MU",         "현재트렌드 · 메모리 3사"),
        ("ASML",       "현재트렌드 · EUV 독점"),
        ("005930.KS",  "현재트렌드 · 삼성전자 (HBM3E)"),
        ("000660.KS",  "현재트렌드 · SK하이닉스 (HBM 1위)"),
        # === 예상 다음 키워드: 빅테크 메가캡 합류 ===
        ("MSFT",       "다음트렌드 · Azure AI"),
        ("GOOGL",      "다음트렌드 · Gemini"),
        ("META",       "다음트렌드 · AI 광고"),
        ("AMZN",       "다음트렌드 · AWS AI"),
    ]

    print("=" * 76)
    print(" 펀더멘털 점검 (yfinance 기반)")
    print("=" * 76)
    for tk, label in targets:
        report(tk, label)
    print("\n" + "=" * 76)


if __name__ == "__main__":
    main()
