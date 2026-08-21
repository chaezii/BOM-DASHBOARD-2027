"""
market_data.py
구글시트에 없는 데이터(이동평균선, 재무 건전성 지표)를 야후 파이낸스(yfinance)에서 가져옵니다.

⚠️ 참고
- 무료 데이터라 가끔 값이 비어있거나 부정확할 수 있어요.
- 국내 종목은 종목코드에 .KS(코스피) / .KQ(코스닥)를 붙여서 찾는데, 100% 정확하진 않습니다.
- 이 파일의 매수/보류/매도 판단은 투자 조언이 아니라, 아래 규칙에 따른 단순 계산 결과입니다.
- 장기 가치투자(워런 버핏/찰리 멍거 식) 관점을 참고해서 규칙을 짰습니다:
  가격이 조금 떨어졌다고 무조건 사거나, 조금 올랐다고 무조건 파는 게 아니라
  '이 회사가 돈을 벌고 있는가(BEP)', '너무 비싸게 사는 건 아닌가(PER)',
  '빚이 과하진 않은가(부채비율)', '내가 원래 배분하려던 비중보다 많이/적게 들고 있는가'를
  같이 봅니다.
"""

from __future__ import annotations

import yfinance as yf


def resolve_yahoo_symbol(market: str, code: str) -> list[str]:
    """market('국내'/'미국' 등)과 종목코드로 야후 파이낸스 심볼 후보들을 순서대로 반환.
    국내는 코스피(.KS)를 먼저, 안되면 코스닥(.KQ)을 시도."""
    code = (code or "").strip()
    if not code:
        return []
    if "국내" in market:
        return [f"{code}.KS", f"{code}.KQ"]
    # 미국/해외는 종목코드 자체가 심볼 (예: AAPL, GOOGL)
    return [code]


def fetch_technical_and_fundamental(market: str, code: str) -> dict:
    """이동평균선 + 장기투자 판단에 쓸 재무 건전성 지표를 가져옴.
    실패하면 해당 항목만 None으로 채워서 반환 (에러로 전체가 죽지 않게)."""
    result = {
        "ma60": None,
        "ma120": None,
        "is_profitable": None,       # BEP(손익분기점) 통과 여부 - 순이익이 흑자인가
        "pe_ratio": None,            # PER - 너무 비싸게 사는 건 아닌지
        "roe_pct": None,             # 자기자본이익률 - 돈을 잘 버는 우량 기업인지
        "debt_to_equity": None,      # 부채비율 - 재무구조가 건전한지
        "week52_high": None,
        "drawdown_from_high_pct": None,  # 52주 고점 대비 몇 % 하락했는지
        "resolved_symbol": None,
    }

    for symbol in resolve_yahoo_symbol(market, code):
        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="260d")
            if hist is None or hist.empty or "Close" not in hist:
                continue

            closes = hist["Close"].dropna()
            if len(closes) >= 60:
                result["ma60"] = float(closes.tail(60).mean())
            if len(closes) >= 120:
                result["ma120"] = float(closes.tail(120).mean())
            elif len(closes) >= 20:
                result["ma120"] = float(closes.mean())  # 상장 얼마 안 된 종목 등 대체값

            if len(closes):
                week52_high = float(closes.max())
                last_price = float(closes.iloc[-1])
                result["week52_high"] = week52_high
                if week52_high:
                    result["drawdown_from_high_pct"] = (last_price - week52_high) / week52_high * 100

            try:
                info = ticker.get_info()
            except Exception:
                info = {}

            net_income = info.get("netIncomeToCommon")
            if net_income is not None:
                result["is_profitable"] = net_income > 0

            result["pe_ratio"] = info.get("trailingPE")
            roe = info.get("returnOnEquity")
            result["roe_pct"] = (roe * 100) if roe is not None else None
            dte = info.get("debtToEquity")
            result["debt_to_equity"] = dte  # yfinance는 보통 %단위(예: 45.2)로 줌

            result["resolved_symbol"] = symbol
            break  # 성공한 심볼을 찾았으면 다음 후보는 시도하지 않음
        except Exception:
            continue

    return result


def fetch_usd_krw_rate() -> float | None:
    """현재 원/달러 환율을 야후 파이낸스에서 가져옴 (1달러 = 몇 원)."""
    try:
        ticker = yf.Ticker("KRW=X")
        hist = ticker.history(period="5d")
        closes = hist["Close"].dropna()
        if len(closes):
            return float(closes.iloc[-1])
    except Exception:
        pass
    return None


def classify_signal(
    avg_buy_price,
    current_price,
    ma120,
    target_weight_pct=None,
    current_weight_pct=None,
    is_profitable=None,
    pe_ratio=None,
    debt_to_equity=None,
) -> dict:
    """
    장기 가치투자 관점의 매수/보류/매도 판단. {"signal": "...", "reasons": [...]} 반환.

    매수 고려 (아래 조건을 최대한 많이 만족할수록 근거가 탄탄함):
      - 필수: 현재비중 < 목표비중 (아직 배분 목표만큼 못 채움 - 더 살 여지가 있음)
      - 필수: 적자 기업이 아님 (BEP 통과, 정보 없으면 통과로 간주)
      - 가산: 실시간가 ≤ 120일 이동평균선 (저가 매수 타이밍)
      - 가산: PER이 지나치게 높지 않음 (< 40, 정보 있을 때만 체크)

    매도 고려 (재무가 흔들리거나, 원래 배분보다 너무 많이 쌓였을 때만):
      - 적자 기업 + 평단가 대비 -20% 이상 하락 (펀더멘털도 깨지고 가격도 깨짐)
      - 또는 현재비중이 목표비중의 1.5배를 초과 (리밸런싱 필요)
      - 또는 부채비율이 200%를 초과 + 적자 (재무 위험 신호)

    보류 : 위 조건에 해당하지 않는 나머지 전부 (기본값 - 우량주는 어지간해선 계속 보유)
    """
    reasons = []

    if avg_buy_price is None or current_price is None or avg_buy_price == 0:
        return {"signal": "—", "reasons": ["평단가/현재가 정보 부족"]}

    has_room_to_buy = (
        target_weight_pct is not None
        and current_weight_pct is not None
        and current_weight_pct < target_weight_pct
    )
    overweight = (
        target_weight_pct is not None
        and current_weight_pct is not None
        and target_weight_pct > 0
        and current_weight_pct > target_weight_pct * 1.5
    )
    not_unprofitable = is_profitable is not False  # None(정보없음)은 통과로 간주
    is_cheap_vs_ma = ma120 is not None and current_price <= ma120
    pe_ok = pe_ratio is None or pe_ratio < 40
    pct_from_buy = (current_price - avg_buy_price) / avg_buy_price * 100
    high_debt_risk = debt_to_equity is not None and debt_to_equity > 200

    # --- 매도 고려 ---
    if is_profitable is False and pct_from_buy <= -20:
        reasons.append("적자 기업 + 평단가 대비 -20% 이상 하락")
        return {"signal": "매도 고려", "reasons": reasons}
    if overweight:
        reasons.append(f"현재비중이 목표비중({target_weight_pct:.0f}%)의 1.5배 초과 - 리밸런싱 필요")
        return {"signal": "매도 고려", "reasons": reasons}
    if high_debt_risk and is_profitable is False:
        reasons.append("부채비율 200% 초과 + 적자 - 재무 위험")
        return {"signal": "매도 고려", "reasons": reasons}

    # --- 매수 고려 ---
    if has_room_to_buy and not_unprofitable:
        if is_cheap_vs_ma:
            reasons.append("목표비중 미달 + 120일 이평선 이하(저가 구간)")
        else:
            reasons.append("목표비중 미달 + 흑자 기업")
        if not pe_ok:
            reasons.append("단, PER이 다소 높아 신중 검토 필요")
        return {"signal": "매수 고려", "reasons": reasons}

    # --- 보류 (기본값) ---
    if target_weight_pct is None or current_weight_pct is None:
        reasons.append("목표비중 정보 없음 - 장기 보유 유지")
    else:
        reasons.append("목표비중 범위 안 · 특별한 매수/매도 근거 없음")
    return {"signal": "보류", "reasons": reasons}
