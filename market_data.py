"""
market_data.py
구글시트에 없는 데이터(60일/120일 이동평균)를 야후 파이낸스(yfinance)에서 가져옵니다.

⚠️ 참고
- 무료 데이터라 가끔 값이 비어있거나 부정확할 수 있어요.
- 국내 종목은 종목코드에 .KS(코스피) / .KQ(코스닥)를 붙여서 찾는데, 100% 정확하진 않습니다.
- 이 파일의 매수/보류/매도 판단은 투자 조언이 아니라, 아래 규칙에 따른 단순 계산 결과입니다.
- 3년 전저점/전고점은 야후 파이낸스에서 빈 값으로 오는 경우가 많아서 판단 기준에서 뺐습니다.
  대신 항상 채워지는 값들(시트의 수익률, 60일/120일 이평선, 목표비중)만 기준으로 씁니다.
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
    """60일/120일 이동평균 종가를 가져옴.
    실패하면 해당 항목만 None으로 채워서 반환 (에러로 전체가 죽지 않게)."""
    result = {
        "ma60": None,
        "ma120": None,
        "resolved_symbol": None,
    }

    for symbol in resolve_yahoo_symbol(market, code):
        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="200d")  # 120일 이평선 계산에 필요한 만큼만 (3y보다 가볍고 빠름)
            if hist is None or hist.empty or "Close" not in hist:
                continue

            closes = hist["Close"].dropna()
            if len(closes) >= 60:
                result["ma60"] = float(closes.tail(60).mean())
            if len(closes) >= 120:
                result["ma120"] = float(closes.tail(120).mean())
            elif len(closes) >= 20:
                result["ma120"] = float(closes.mean())  # 상장 얼마 안 된 종목 등 대체값

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


def _safe_float(v):
    """None/문자열/NaN 등을 안전하게 float로, 실패하면 None."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN 체크 (NaN은 자기 자신과도 같지 않음)
        return None
    return f


def classify_signal(
    return_pct,
    current_price,
    ma60,
    ma120,
    target_weight_pct=None,
    current_weight_pct=None,
) -> dict:
    """
    시트 수익률 · 60일/120일 이동평균선 · 목표비중만으로 판단.
    {"signal": "...", "reasons": [...]} 반환.

    매수 고려 (아래 2가지를 전부 만족할 때만 - AND):
      - 현재비중 < 목표비중 (아직 배분 목표만큼 못 채움)
      - 실시간가 ≤ 60일 이동평균선 AND 실시간가 ≤ 120일 이동평균선 (둘 다 아래 - 확실한 조정 구간)

    매도 고려 (아래 2가지를 전부 만족할 때만 - AND):
      - 수익률(시트 기준) -30% 이하
      - 현재비중이 목표비중의 1.5배 초과

    보류 : 위 두 경우가 아닌 나머지 전부 (기본값)

    ⚠️ 값이 이상하게 들어와도(문자열 섞임, NaN 등) 절대 에러를 던지지 않고
    안전하게 "—"(판단 불가)를 반환합니다.
    """
    try:
        return _classify_signal_inner(
            return_pct, current_price, ma60, ma120,
            target_weight_pct, current_weight_pct,
        )
    except Exception as e:
        return {"signal": "—", "reasons": [f"판단 계산 중 오류 ({type(e).__name__})"]}


def _classify_signal_inner(
    return_pct,
    current_price,
    ma60,
    ma120,
    target_weight_pct,
    current_weight_pct,
) -> dict:
    return_pct = _safe_float(return_pct)
    current_price = _safe_float(current_price)
    ma60 = _safe_float(ma60)
    ma120 = _safe_float(ma120)
    target_weight_pct = _safe_float(target_weight_pct)
    current_weight_pct = _safe_float(current_weight_pct)

    if return_pct is None:
        return {"signal": "—", "reasons": ["수익률 정보 부족"]}

    has_weight_info = target_weight_pct is not None and current_weight_pct is not None
    has_room_to_buy = has_weight_info and current_weight_pct < target_weight_pct
    overweight = has_weight_info and target_weight_pct > 0 and current_weight_pct > target_weight_pct * 1.5

    below_ma60 = ma60 is not None and current_price is not None and current_price <= ma60
    below_ma120 = ma120 is not None and current_price is not None and current_price <= ma120
    is_dip = below_ma60 and below_ma120  # 60일선·120일선 둘 다 아래 - 확실한 조정 구간

    reasons = []

    # --- 매도 고려 (AND, 2가지 모두 충족해야 함) ---
    heavy_loss = return_pct <= -30
    if heavy_loss and overweight:
        reasons.append(f"수익률 {return_pct:.1f}% (-30% 이하) + 현재비중이 목표비중({target_weight_pct:.1f}%)의 1.5배 초과")
        return {"signal": "매도 고려", "reasons": reasons}

    # --- 매수 고려 (AND, 2가지 모두 충족해야 함) ---
    if has_room_to_buy and is_dip:
        reasons.append("목표비중 미달 + 60일·120일 이평선 모두 아래(조정 구간)")
        return {"signal": "매수 고려", "reasons": reasons}

    # --- 보류 (기본값) - 매수 조건 중 뭐가 안 맞는지 설명 ---
    missing = []
    if not has_weight_info:
        missing.append("목표/현재비중 정보 없음")
    elif not has_room_to_buy:
        missing.append("이미 목표비중 충족")
    if not below_ma60:
        missing.append("60일 이평선 위")
    if not below_ma120:
        missing.append("120일 이평선 위")
    reasons.append("매수 조건 일부 미충족: " + ", ".join(missing) if missing else "특별한 매수/매도 신호 없음")
    return {"signal": "보류", "reasons": reasons}
