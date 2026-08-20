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
            number={"suffix": "%", "font": {"size": 36}},
            title={"text": title, "font": {"size": 16}},
            gauge={
                "axis": {"range": [0, 100], "tickcolor": "#8a94a6"},
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
# 자산 구성 + 주식 요약
# ---------------------------------------------------------------------------
c3, c4 = st.columns(2)
with c3:
    st.subheader("자산 구성")
    labels, values = [], []
    for key, label in [
        ("real_estate", "부동산"),
        ("stocks", "주식"),
        ("pension", "퇴직연금"),
        ("cash", "현금"),
        ("etc", "기타"),
        ("crypto", "가상화폐"),
    ]:
        v = asset.get(key)
        if v:
            labels.append(label)
            values.append(v)
    fig = go.Figure(go.Pie(labels=labels, values=values, hole=0.6))
    fig.update_layout(
        height=320,
        paper_bgcolor="#12171f",
        font={"color": "#e8ecf1"},
        margin=dict(l=10, r=10, t=10, b=10),
    )
    st.plotly_chart(fig, use_container_width=True)

with c4:
    st.subheader("주식 포트폴리오 요약")
    st.metric("총 매수금액", money(stock.get("total_buy")))
    st.metric("총 평가금액", money(stock.get("total_eval")))
    st.metric("평가손익", money(stock.get("total_profit")))
    st.metric("수익률", f"{stock.get('total_return_pct') or 0:.1f}%")

st.divider()

# ---------------------------------------------------------------------------
# 가계부 월별 추이
# ---------------------------------------------------------------------------
st.subheader("가계부 · 월별 수입/지출/저축")
if ledger:
    months = [m["date"] for m in ledger]
    income = [m["income"] or 0 for m in ledger]
    expense = [m["expense"] or 0 for m in ledger]
    fig = go.Figure()
    fig.add_bar(x=months, y=income, name="수입", marker_color="#34d8b0")
    fig.add_bar(x=months, y=expense, name="지출", marker_color="#ff6b6b")
    fig.update_layout(
        barmode="group",
        height=320,
        paper_bgcolor="#12171f",
        plot_bgcolor="#12171f",
        font={"color": "#e8ecf1"},
        legend=dict(orientation="h"),
    )
    st.plotly_chart(fig, use_container_width=True)

    filled_income = [m for m in ledger if m["income"]]
    if len(filled_income) < len(ledger) / 2:
        st.warning(
            "가계부에 수입이 입력된 달이 적어서(전체 중 일부만) 실제 저축여력을 "
            "정확히 계산할 수 없습니다. 매달 수입을 입력하면 이 대시보드가 더 정확해집니다."
        )
else:
    st.info("가계부 데이터를 찾지 못했습니다. 디버그 모드를 켜고 fetch_data.py의 라벨 검색 로직을 확인하세요.")

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
    df_assets = pd.DataFrame(rows)
    st.dataframe(
        df_assets.style.format(
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
                        "수익률": t["return_pct"],
                    }
                )
            if rows:
                df_t = pd.DataFrame(rows)
                st.dataframe(
                    df_t.style.format(
                        {
                            "보유수량": "{:,.0f}",
                            "평가금액(이번달)": "{:,.0f}원",
                            "평가금액(지난달)": "{:,.0f}원",
                            "증감": "{:+,.0f}원",
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

st.caption("이 페이지는 열릴 때마다(최대 10분 캐시) 구글시트 최신 값을 다시 읽어옵니다.")
