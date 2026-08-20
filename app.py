"""
app.py
Streamlit 대시보드. `streamlit run app.py`로 로컬 실행,
Streamlit Community Cloud에 배포하면 고정 웹 링크가 생깁니다.
링크에 접속할 때마다(최대 10분 캐시) 구글시트 최신값을 다시 읽어옵니다.
"""

import json
from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from fetch_data import fetch_all
from sheet_utils import to_number

# ---------------------------------------------------------------------------
# 설정: 목표
# ---------------------------------------------------------------------------
GOAL_NET_WORTH = 1_000_000_000
GOAL_CASH = 100_000_000
DEADLINE = date(2027, 12, 31)

st.set_page_config(page_title="통합 자산 대시보드", page_icon="\U0001F4C8", layout="wide")


@st.cache_data(ttl=600)  # 10분 캐시 - 너무 자주 시트를 읽지 않도록
def load_data(_sa_info_json: str, _history_sheet_id: str | None, debug: bool):
    sa_info = json.loads(_sa_info_json)
    return fetch_all(sa_info, history_sheet_id=_history_sheet_id, debug=debug)


def money(v):
    if v is None:
        return "-"
    return f"{v:,.0f}원"


def eok(v):
    if v is None:
        return "-"
    return f"{v/100_000_000:.2f}억"


def gauge(value, goal, title, color):
    pct = 0 if not goal else min(value / goal * 100, 100)
    fig = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=pct,
            number={"suffix": "%", "font": {"size": 36, "color": "#e8ecf1"}},
            title={"text": title, "font": {"size": 16, "color": "#e8ecf1"}},
            gauge={
                "axis": {"range": [0, 100], "tickcolor": "#8a94a6", "tickfont": {"color": "#8a94a6"}},
                "bar": {"color": color},
                "bgcolor": "#12171f",
                "borderwidth": 0,
            },
        )
    )
    fig.update_layout(
        height=220,
        margin=dict(l=20, r=20, t=50, b=10),
        paper_bgcolor="#12171f",
        font={"color": "#e8ecf1"},
    )
    return fig


# ---------------------------------------------------------------------------
# 사이드바: 인증 / 디버그
# ---------------------------------------------------------------------------
st.sidebar.header("설정")
debug_mode = st.sidebar.checkbox("디버그 모드 (콘솔에 원본 값 출력)", value=False)

if "gcp_service_account" not in st.secrets:
    st.error(
        "st.secrets['gcp_service_account']가 없습니다. "
        ".streamlit/secrets.toml (로컬) 또는 Streamlit Cloud > Settings > Secrets 에 "
        "서비스 계정 JSON을 등록하세요. README.md 참고."
    )
    st.stop()

sa_info_json = json.dumps(dict(st.secrets["gcp_service_account"]))

history_sheet_id = None
if "app" in st.secrets and st.secrets["app"].get("history_sheet_id"):
    history_sheet_id = st.secrets["app"]["history_sheet_id"]

try:
    data = load_data(sa_info_json, history_sheet_id, debug_mode)
except Exception as e:
    st.error(f"구글시트 연결/파싱 중 오류가 발생했습니다: {e}")
    st.info(
        "시트를 서비스 계정 이메일과 공유했는지, sheet_utils의 라벨 검색이 "
        "실제 시트 구조와 맞는지 확인하세요. 디버그 모드를 켜고 터미널 로그를 보세요."
    )
    st.stop()

asset = data["asset"]
stock = data["stock"]
ledger = data["ledger"]

net_worth = asset.get("net_worth") or 0
cash = asset.get("cash") or 0

days_left = (DEADLINE - date.today()).days
months_left = max(days_left / 30.4, 0.1)

# ---------------------------------------------------------------------------
# 헤더
# ---------------------------------------------------------------------------
st.markdown(
    f"<div style='color:#d4af37;font-family:monospace;font-size:12px;letter-spacing:.1em;'>"
    f"{date.today().isoformat()} SNAPSHOT · LIVE FROM GOOGLE SHEETS</div>",
    unsafe_allow_html=True,
)
st.title("순자산 10억, 현금 1억 — 2027년까지")
st.caption(f"목표 시한 {DEADLINE.isoformat()} · 남은 기간 약 {days_left}일 ({months_left:.1f}개월)")

# ---------------------------------------------------------------------------
# 목표 게이지
# ---------------------------------------------------------------------------
c1, c2 = st.columns(2)
with c1:
    st.plotly_chart(gauge(net_worth, GOAL_NET_WORTH, "순자산 목표 진행률", "#34d8b0"), use_container_width=True)
    gap = GOAL_NET_WORTH - net_worth
    st.metric("현재 순자산", eok(net_worth), delta=f"목표까지 {eok(gap)} 남음")
    if gap > 0:
        st.caption(f"필요 페이스: 월 {money(gap/months_left)}")

with c2:
    st.plotly_chart(gauge(cash, GOAL_CASH, "현금 목표 진행률", "#ff6b6b"), use_container_width=True)
    gap_c = GOAL_CASH - cash
    st.metric("현재 현금", eok(cash), delta=f"목표까지 {eok(gap_c)} 남음")
    if gap_c > 0:
        st.caption(f"필요 페이스: 월 {money(gap_c/months_left)}")

st.divider()

# ---------------------------------------------------------------------------
# 자산 구성 (가로 막대 - 작은 항목도 겹치지 않고 잘 보이도록)
# ---------------------------------------------------------------------------
st.subheader("자산 구성")
comp_items = []
for key, label, color in [
    ("real_estate", "부동산", "#5b9dff"),
    ("stocks", "주식", "#34d8b0"),
    ("pension", "퇴직연금", "#d4af37"),
    ("cash", "현금", "#ff6b6b"),
    ("etc", "기타", "#8a94a6"),
    ("crypto", "가상화폐", "#a78bfa"),
]:
    v = asset.get(key)
    if v:
        comp_items.append((label, v, color))

if comp_items:
    comp_items.sort(key=lambda x: x[1])  # 작은 값이 위, 큰 값이 아래로 (가로 막대 관례)
    total_comp = sum(v for _, v, _ in comp_items)
    labels = [c[0] for c in comp_items]
    vals = [c[1] for c in comp_items]
    colors = [c[2] for c in comp_items]
    pct_text = [f"{v/total_comp*100:.1f}%  ({v:,.0f}원)" for v in vals]

    fig = go.Figure(
        go.Bar(
            x=vals,
            y=labels,
            orientation="h",
            marker=dict(color=colors),
            text=pct_text,
            textposition="outside",
            textfont=dict(color="#e8ecf1", size=13),
            hovertemplate="%{y}: %{x:,.0f}원<extra></extra>",
        )
    )
    fig.update_layout(
        height=80 + 46 * len(labels),
        paper_bgcolor="#12171f",
        plot_bgcolor="#12171f",
        font={"color": "#e8ecf1"},
        margin=dict(l=10, r=90, t=10, b=10),
        xaxis=dict(showticklabels=False, showgrid=False, zeroline=False),
        yaxis=dict(tickfont=dict(size=13)),
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("자산 구성 데이터를 찾지 못했습니다.")

st.divider()

# ---------------------------------------------------------------------------
# 자산현황 상세 항목 (전월 대비)
# ---------------------------------------------------------------------------
st.subheader("자산현황 상세 항목")
if not history_sheet_id:
    st.info(
        "전월 대비를 보려면 '기록용 시트'를 연결해야 해요. "
        "README의 '기록용 시트 만들기' 단계를 따라 secrets에 history_sheet_id를 추가해주세요."
    )

asset_items = asset.get("items", {})
asset_prev = data.get("asset_prev_items", {})

if asset_items:
    rows = []
    for name, cur_val in asset_items.items():
        prev_val = asset_prev.get(name)
        delta = (cur_val - prev_val) if (prev_val is not None) else None
        rows.append(
            {
                "항목": name,
                "이번 달": cur_val,
                "지난달": prev_val if prev_val is not None else None,
                "증감": delta,
            }
        )

    total_cur = sum(r["이번 달"] for r in rows)
    total_prev_vals = [r["지난달"] for r in rows if r["지난달"] is not None]
    total_prev = sum(total_prev_vals) if len(total_prev_vals) == len(rows) else None
    total_delta = (total_cur - total_prev) if total_prev is not None else None
    rows.append(
        {
            "항목": "합계",
            "이번 달": total_cur,
            "지난달": total_prev,
            "증감": total_delta,
        }
    )

    df_assets = pd.DataFrame(rows)

    def _highlight_total(row):
        is_total = row["항목"] == "합계"
        return ["font-weight: bold; border-top: 2px solid #8a94a6" if is_total else "" for _ in row]

    st.dataframe(
        df_assets.style.apply(_highlight_total, axis=1).format(
            {"이번 달": "{:,.0f}원", "지난달": "{:,.0f}원", "증감": "{:+,.0f}원"},
            na_rep="—",
        ),
        use_container_width=True,
        hide_index=True,
    )
    if not asset_prev:
        st.caption("아직 지난달 기록이 없어서 증감이 비어있어요. 다음 달부터 채워집니다.")
else:
    st.info("자산 상세 항목을 찾지 못했습니다. 디버그 모드를 켜고 로그를 확인해주세요.")

st.divider()

# ---------------------------------------------------------------------------
# 가계부 · 수입 vs 지출 (단순 비교 막대)
# ---------------------------------------------------------------------------
st.subheader("가계부 · 수입 vs 지출")
if ledger:
    months = [m["date"] for m in ledger]
    income_vals = [m["income"] or 0 for m in ledger]
    expense_vals = [m["expense"] or 0 for m in ledger]

    fig = go.Figure()
    fig.add_bar(
        x=months, y=income_vals, name="수입",
        marker_color="#34d8b0",
        text=[f"{v:,.0f}" for v in income_vals],
        textposition="outside",
        textfont=dict(color="#e8ecf1", size=11),
        hovertemplate="수입 %{y:,.0f}원<extra></extra>",
    )
    fig.add_bar(
        x=months, y=expense_vals, name="지출",
        marker_color="#ff6b6b",
        text=[f"{v:,.0f}" for v in expense_vals],
        textposition="outside",
        textfont=dict(color="#e8ecf1", size=11),
        hovertemplate="지출 %{y:,.0f}원<extra></extra>",
    )
    fig.update_layout(
        barmode="group",
        height=360,
        paper_bgcolor="#12171f",
        plot_bgcolor="#12171f",
        font={"color": "#e8ecf1"},
        legend=dict(orientation="h", y=1.12),
        margin=dict(t=40, b=10),
        yaxis=dict(gridcolor="#232b36", tickfont=dict(color="#8a94a6")),
        xaxis=dict(gridcolor="#232b36"),
    )
    st.plotly_chart(fig, use_container_width=True)

    filled_income = [m for m in ledger if m["income"]]
    if len(filled_income) < len(ledger) / 2:
        st.warning(
            "가계부에 수입이 입력된 달이 적어서(전체 중 일부만) 실제 저축여력을 "
            "정확히 계산할 수 없습니다. 매달 수입을 입력하면 이 비교가 더 정확해집니다."
        )
else:
    st.info("가계부 데이터를 찾지 못했습니다. 디버그 모드를 켜고 fetch_data.py의 라벨 검색 로직을 확인하세요.")

st.divider()

# ---------------------------------------------------------------------------
# 소비관리 (카테고리별 월간 지출) - 자산현황 파일의 '소비관리' 탭
# ---------------------------------------------------------------------------
st.subheader("소비관리 · 카테고리별 지출")

spending = data.get("spending") or {}
sp_categories = spending.get("categories") or {}
sp_months = spending.get("months") or []

has_spending_data = sp_categories and any(sum(v) > 0 for v in sp_categories.values())

if has_spending_data:
    cat_colors = ["#5b9dff", "#34d8b0", "#d4af37", "#ff6b6b", "#a78bfa", "#f59e0b", "#8a94a6"]
    fig = go.Figure()
    for i, (cat_name, monthly_vals) in enumerate(sp_categories.items()):
        fig.add_bar(
            x=sp_months, y=monthly_vals, name=cat_name,
            marker_color=cat_colors[i % len(cat_colors)],
            hovertemplate=f"{cat_name} %{{y:,.0f}}원<extra></extra>",
        )
    fig.update_layout(
        barmode="stack",
        height=380,
        paper_bgcolor="#12171f",
        plot_bgcolor="#12171f",
        font={"color": "#e8ecf1"},
        legend=dict(orientation="h", y=1.15),
        margin=dict(t=50, b=10),
        yaxis=dict(gridcolor="#232b36", tickfont=dict(color="#8a94a6")),
        xaxis=dict(gridcolor="#232b36"),
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Eat·Live·Wear·Enjoy·Edu·Ride·Other 카테고리별 지출을 월별로 쌓아서 보여줘요.")
else:
    st.info(
        "소비관리 탭이 아직 비어있어요. 시트에 카테고리별 지출이 채워지면 "
        "이 자리에 자동으로 그래프가 나타납니다 (코드 수정 필요 없음)."
    )

st.divider()

# ---------------------------------------------------------------------------
# 주식 포트폴리오 요약 (한 줄, 작은 글씨)
# ---------------------------------------------------------------------------
st.subheader("주식 포트폴리오 요약")


def compact_metric_row(items):
    cols = st.columns(len(items))
    for col, (label, value, color) in zip(cols, items):
        col.markdown(
            f"""
            <div style="background:#161c26;border:1px solid #232b36;border-radius:10px;
                        padding:10px 14px;">
              <div style="font-size:11px;color:#8a94a6;margin-bottom:4px;">{label}</div>
              <div style="font-size:17px;font-weight:600;color:{color};
                          font-family:'IBM Plex Mono',monospace;">{value}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


_buy = stock.get("total_buy")
_eval = stock.get("total_eval")
_profit = stock.get("total_profit")
_return = stock.get("total_return_pct")

compact_metric_row(
    [
        ("총 매수금액", money(_buy), "#e8ecf1"),
        ("총 평가금액", money(_eval), "#e8ecf1"),
        ("평가손익", money(_profit), "#34d8b0" if (_profit or 0) >= 0 else "#ff6b6b"),
        ("수익률", f"{_return:.1f}%" if _return is not None else "—", "#34d8b0" if (_return or 0) >= 0 else "#ff6b6b"),
    ]
)
if _buy is not None and _eval is None:
    st.caption(
        "⚠️ 평가금액/수익률이 비어있어요 — 실시간 시세 수식이 아직 값을 못 불러왔을 가능성이 높습니다. "
        "잠시 후(1~2분 뒤) 새로고침해보세요."
    )

# --- 당월 / 3개월전 / 6개월전 추이 (차트) ---
stock_trend = data.get("stock_trend") or {}
if stock_trend:
    st.markdown("<div style='font-size:12px;color:#8a94a6;margin-top:18px;margin-bottom:6px;'>기간별 평가금액 추이</div>", unsafe_allow_html=True)

    trend_points = []
    for key, label in [("6m_ago", "6개월 전"), ("3m_ago", "3개월 전"), ("current", "당월")]:
        snap = stock_trend.get(key)
        trend_points.append(
            {
                "label": label,
                "period": (snap or {}).get("period"),
                "eval": (snap or {}).get("total_eval"),
                "return_pct": (snap or {}).get("total_return_pct"),
            }
        )

    x_labels = [p["label"] for p in trend_points]
    y_vals = [p["eval"] if p["eval"] is not None else 0 for p in trend_points]
    bar_colors = ["#5b9dff" if p["eval"] is not None else "#232b36" for p in trend_points]
    text_labels = []
    for p in trend_points:
        if p["eval"] is None:
            text_labels.append("데이터 없음")
        else:
            rp = f" ({p['return_pct']:.1f}%)" if p["return_pct"] is not None else ""
            text_labels.append(f"{p['eval']:,.0f}원{rp}")

    fig = go.Figure(
        go.Bar(
            x=x_labels,
            y=y_vals,
            marker_color=bar_colors,
            text=text_labels,
            textposition="outside",
            textfont=dict(color="#e8ecf1", size=12),
            hovertemplate="%{x}: %{text}<extra></extra>",
        )
    )
    fig.update_layout(
        height=260,
        paper_bgcolor="#12171f",
        plot_bgcolor="#12171f",
        font={"color": "#e8ecf1"},
        margin=dict(t=30, b=10, l=10, r=10),
        yaxis=dict(showticklabels=False, showgrid=False, zeroline=False),
        xaxis=dict(tickfont=dict(size=13)),
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True)

    if not history_sheet_id:
        st.caption("3개월/6개월 전 값을 보려면 기록용 시트를 연결해야 해요 (README '기록용 시트 만들기' 참고).")
    elif not stock_trend.get("3m_ago") and not stock_trend.get("6m_ago"):
        st.caption("아직 3개월/6개월 치 기록이 쌓이지 않았어요. 계속 사용하시면 자동으로 채워집니다.")

st.divider()

# ---------------------------------------------------------------------------
# 주식 종목별 상세 (전월 대비)
# ---------------------------------------------------------------------------
st.subheader("주식 종목별 현황")

tickers = stock.get("tickers", [])
ticker_prev = data.get("ticker_prev", {})

if tickers:
    markets = sorted(set(t["market"] for t in tickers))
    tabs = st.tabs(markets)
    for tab, market in zip(tabs, markets):
        with tab:
            rows = []
            for t in tickers:
                if t["market"] != market:
                    continue
                key = f"{t['market']}|{t['account']}|{t['code']}"
                prev = ticker_prev.get(key)
                prev_eval = to_number(prev["eval_amount"]) if (prev and prev.get("eval_amount")) else None
                delta = (t["eval_amount"] - prev_eval) if (prev_eval is not None and t["eval_amount"] is not None) else None
                rows.append(
                    {
                        "종목명": t["name"],
                        "계좌": t["account"],
                        "보유수량": t["quantity"],
                        "평가금액(이번달)": t["eval_amount"],
                        "평가금액(지난달)": prev_eval,
                        "증감": delta,
                        "평가손익": t["profit"],
                        "수익률": t["return_pct"],
                    }
                )
            if rows:
                total_cur = sum(r["평가금액(이번달)"] or 0 for r in rows)
                prev_vals = [r["평가금액(지난달)"] for r in rows]
                total_prev = sum(prev_vals) if all(v is not None for v in prev_vals) else None
                total_delta = (total_cur - total_prev) if total_prev is not None else None

                total_buy = sum(
                    (t["buy_amount"] or 0) for t in tickers if t["market"] == market
                )
                total_profit = sum(
                    (t["profit"] or 0) for t in tickers if t["market"] == market
                )
                total_return = (total_profit / total_buy * 100) if total_buy else None

                rows.append(
                    {
                        "종목명": "합계",
                        "계좌": "",
                        "보유수량": None,
                        "평가금액(이번달)": total_cur,
                        "평가금액(지난달)": total_prev,
                        "증감": total_delta,
                        "평가손익": total_profit,
                        "수익률": total_return,
                    }
                )

                df_t = pd.DataFrame(rows)

                def _highlight_total(row):
                    is_total = row["종목명"] == "합계"
                    return ["font-weight: bold; border-top: 2px solid #8a94a6" if is_total else "" for _ in row]

                st.dataframe(
                    df_t.style.apply(_highlight_total, axis=1).format(
                        {
                            "보유수량": "{:,.0f}",
                            "평가금액(이번달)": "{:,.0f}원",
                            "평가금액(지난달)": "{:,.0f}원",
                            "증감": "{:+,.0f}원",
                            "평가손익": "{:+,.0f}원",
                            "수익률": "{:.1f}%",
                        },
                        na_rep="—",
                    ),
                    use_container_width=True,
                    hide_index=True,
                )
    if not ticker_prev:
        st.caption("아직 지난달 기록이 없어서 증감이 비어있어요. 다음 달부터 채워집니다.")
else:
    st.info("종목별 데이터를 찾지 못했습니다. 디버그 모드를 켜고 로그를 확인해주세요.")

st.divider()

# ---------------------------------------------------------------------------
# 매수/보류/매도 판단 (60일·120일 이평선 + 재무데이터, 야후 파이낸스 연동)
# ---------------------------------------------------------------------------
st.subheader("종목별 매수 · 보류 · 매도 판단")
st.caption(
    "⚠️ 투자 조언이 아니라 아래 규칙에 따른 단순 계산 결과입니다. "
    "매수 고려: 실시간가 ≤ 120일 이평선 · 보류: 평단가 대비 ±5~10% · 매도 고려: 평단가 대비 -20% 이하"
)

if tickers:
    @st.cache_data(ttl=6 * 60 * 60)  # 6시간 캐시 - 야후 파이낸스 호출을 너무 자주 하지 않도록
    def _load_market_data(market: str, code: str):
        import market_data
        return market_data.fetch_technical_and_fundamental(market, code)

    import market_data

    signal_tabs = st.tabs(markets)
    for tab, market in zip(signal_tabs, markets):
        with tab:
            with st.spinner(f"{market} 종목의 시세/재무 데이터를 불러오는 중..."):
                sig_rows = []
                for t in tickers:
                    if t["market"] != market:
                        continue
                    md = _load_market_data(t["market"], t["code"])
                    signal = market_data.classify_signal(t["avg_buy_price"], t["price"], md["ma120"])
                    sig_rows.append(
                        {
                            "종목명": t["name"],
                            "계좌": t["account"],
                            "구매평단가": t["avg_buy_price"],
                            "실시간평단가": t["price"],
                            "60일 이평선": md["ma60"],
                            "120일 이평선": md["ma120"],
                            "기업매출": md["revenue"],
                            "순이익": md["net_income"],
                            "성장률": md["revenue_growth_pct"],
                            "판단": signal,
                        }
                    )

            if sig_rows:
                df_sig = pd.DataFrame(sig_rows)

                def _signal_color(row):
                    colors = {
                        "매수 고려": "color:#34d8b0;font-weight:600;",
                        "매도 고려": "color:#ff6b6b;font-weight:600;",
                        "보류": "color:#d4af37;font-weight:600;",
                        "관망": "color:#8a94a6;",
                    }
                    style = colors.get(row["판단"], "")
                    return ["" if col != "판단" else style for col in row.index]

                st.dataframe(
                    df_sig.style.apply(_signal_color, axis=1).format(
                        {
                            "구매평단가": "{:,.0f}원",
                            "실시간평단가": "{:,.0f}원",
                            "60일 이평선": "{:,.0f}원",
                            "120일 이평선": "{:,.0f}원",
                            "기업매출": "{:,.0f}",
                            "순이익": "{:,.0f}",
                            "성장률": "{:.1f}%",
                        },
                        na_rep="—",
                    ),
                    use_container_width=True,
                    hide_index=True,
                )
    st.caption(
        "60일/120일 이평선과 재무데이터는 야후 파이낸스 무료 데이터라 비어있거나 다소 부정확할 수 있어요. "
        "국내 종목은 코스피(.KS)/코스닥(.KQ)을 자동으로 시도해서 찾습니다."
    )
else:
    st.info("종목 데이터가 없어서 판단표를 만들 수 없습니다.")

st.caption("이 페이지는 열릴 때마다(최대 10분 캐시) 구글시트 최신 값을 다시 읽어옵니다.")
