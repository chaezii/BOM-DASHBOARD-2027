"""
market_data.py
구글시트에 없는 데이터(이동평균선, 기업 매출/순이익/성장률)를
야후 파이낸스(yfinance)에서 가져옵니다.

⚠️ 참고
- 무료 데이터라 가끔 값이 비어있거나 부정확할 수 있어요.
- 국내 종목은 종목코드에 .KS(코스피) / .KQ(코스닥)를 붙여서 찾는데, 100% 정확하진 않습니다.
- 이 파일의 매수/보류/매도 판단은 투자 조언이 아니라, 아래 규칙에 따른 단순 계산 결과입니다.
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
    """60일/120일 이동평균 종가, 매출, 순이익, 매출 성장률을 가져옴.
    실패하면 해당 항목만 None으로 채워서 반환 (에러로 전체가 죽지 않게)."""
    result = {
        "ma60": None,
        "ma120": None,
        "revenue": None,
        "net_income": None,
        "revenue_growth_pct": None,
        "resolved_symbol": None,
    }

    for symbol in resolve_yahoo_symbol(market, code):
        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="200d")
            if hist is None or hist.empty or "Close" not in hist:
                continue

            closes = hist["Close"].dropna()
            if len(closes) >= 60:
                result["ma60"] = float(closes.tail(60).mean())
            if len(closes) >= 120:
                result["ma120"] = float(closes.tail(120).mean())
            elif len(closes) >= 20:
                # 상장한지 얼마 안 된 종목 등, 120일치가 없으면 있는 만큼으로 대체
                result["ma120"] = float(closes.mean())

            try:
                info = ticker.get_info()
            except Exception:
                info = {}
            result["revenue"] = info.get("totalRevenue")
            result["net_income"] = info.get("netIncomeToCommon")
            growth = info.get("revenueGrowth")
            result["revenue_growth_pct"] = (growth * 100) if growth is not None else None

            result["resolved_symbol"] = symbol
            break  # 성공한 심볼을 찾았으면 다음 후보는 시도하지 않음
        except Exception:
            continue

    return result


def classify_signal(avg_buy_price, current_price, ma120) -> str:
    """
    매수 고려 : 실시간가가 120일 이동평균선 이하로 떨어졌을 경우 (최우선)
    매도 고려 : 구매 평단가 대비 실시간가가 20% 이상 하락한 경우
    보류      : 위 두 경우가 아닌 모든 경우 (기본값)
    """
    if avg_buy_price is None or current_price is None or avg_buy_price == 0:
        return "—"

    if ma120 is not None and current_price <= ma120:
        return "매수 고려"

    pct = (current_price - avg_buy_price) / avg_buy_price * 100

    if pct <= -20:
        return "매도 고려"

    return "보류"
