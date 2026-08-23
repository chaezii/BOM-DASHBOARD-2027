"""
app.py
Streamlit 대시보드. `streamlit run app.py`로 로컬 실행,
Streamlit Community Cloud에 배포하면 고정 웹 링크가 생깁니다.
링크에 접속할 때마다(최대 10분 캐시) 구글시트 최신값을 다시 읽어옵니다.
"""

import json
import re
from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from fetch_data import fetch_all, get_client
from sheet_utils import to_number
import history_store

# ---------------------------------------------------------------------------
# 설정: 목표
# ---------------------------------------------------------------------------
GOAL_NET_WORTH = 1_000_000_000
GOAL_CASH = 100_000_000
DEADLINE = date(2027, 12, 31)
PLAN_DEADLINE = "2027-12"

# 소비관리 탭(Eat/Live/Wear/Enjoy/Edu/Ride/Other)과 동일한 카테고리의 월 지출 목표
SPENDING_TARGETS = [
    ("Eat", "먹고 마시는 모든 지출", 900_000),
    ("Live", "주거와 생활 관련 모든 지출", 2_158_333),
    ("Wear", "입고 꾸미는 모든 지출", 300_000),
    ("Enjoy", "문화·여행 등 즐기는 지출", 500_000),
    ("Edu", "교육과 자녀 관련 지출", 100_000),
    ("Ride", "교통 관련 지출", 200_000),
    ("Other", "기타 지출", 300_000),
]
SPENDING_TARGET_TOTAL = 4_500_000  # 사용자가 지정한 공식 목표 총액 (개별 합산 4,458,333과 소폭 차이)

st.set_page_config(page_title="통합 자산 대시보드", page_icon="\U0001F4C8", layout="wide")


@st.cache_data(ttl=1800)  # 30분 캐시 - 구글시트 API 할당량(분당 요청 수)을 아끼기 위해
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
elif st.secrets.get("history_sheet_id"):  # [app] 섹션 없이 최상위에 넣은 경우도 지원
    history_sheet_id = st.secrets["history_sheet_id"]

if debug_mode:
    st.sidebar.caption(
        f"history_sheet_id 인식: {'✅ ' + history_sheet_id[:10] + '...' if history_sheet_id else '❌ 못 찾음 (Secrets의 [app] 섹션과 history_sheet_id 키 이름을 확인하세요)'}"
    )


@st.cache_resource
def _get_gc_client():
    return get_client(json.loads(sa_info_json))


anthropic_api_key = None
if "app" in st.secrets and st.secrets["app"].get("anthropic_api_key"):
    anthropic_api_key = st.secrets["app"]["anthropic_api_key"]

try:
    data = load_data(sa_info_json, history_sheet_id, debug_mode)
except Exception as e:
    err_text = str(e)
    if "429" in err_text or "Quota exceeded" in err_text or "RESOURCE_EXHAUSTED" in err_text:
        st.error("구글시트 API 요청이 순간적으로 너무 많이 몰렸어요 (분당 요청 한도 초과).")
        st.info(
            "**1분 정도 기다렸다가 새로고침**하면 대부분 해결돼요. "
            "코드를 방금 바꾸셨다면(재배포 직후) 캐시가 초기화돼서 한 번에 많이 읽다가 발생한 걸 수 있어요 — "
            "잠시 후 다시 열어보시면 그 다음부턴 30분 캐시 덕분에 잘 안 생깁니다."
        )
    else:
        st.error(f"구글시트 연결/파싱 중 오류가 발생했습니다: {e}")
        st.info(
            "시트를 서비스 계정 이메일과 공유했는지, sheet_utils의 라벨 검색이 "
            "실제 시트 구조와 맞는지 확인하세요. 디버그 모드를 켜고 터미널 로그를 보세요."
        )
    st.stop()

asset = data["asset"]
stock = data["stock"]
ledger = data["ledger"]
spending = data.get("spending") or {}
current_ym = data.get("year_month") or date.today().strftime("%Y-%m")
tickers = stock.get("tickers", [])

sp_categories = spending.get("categories") or {}
sp_months = spending.get("months") or []  # ["1월",...,"12월"] - 시트가 그 해 전체를 담고 있어서 인덱스로 접근
_current_month_idx = date.today().month - 1  # 0-based


def category_actual_this_month(cat_name: str):
    vals = sp_categories.get(cat_name)
    if not vals or _current_month_idx >= len(vals):
        return None
    v = vals[_current_month_idx]
    return v if v else None


net_worth = asset.get("net_worth") or 0
cash = asset.get("cash") or 0
networth_history = data.get("networth_history") or []

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
# 이번 달 인사이트 (AI 코멘트, 월 1회 생성)
# ---------------------------------------------------------------------------
if anthropic_api_key:
    st.markdown("<div style='height:6px;'></div>", unsafe_allow_html=True)

    def _build_insight_data_text() -> str:
        lines = []
        lines.append(f"기준월: {current_ym}")
        lines.append(f"순자산: {net_worth:,.0f}원 (목표 {GOAL_NET_WORTH:,.0f}원, {net_worth/GOAL_NET_WORTH*100:.1f}%)")
        lines.append(f"현금: {cash:,.0f}원 (목표 {GOAL_CASH:,.0f}원, {cash/GOAL_CASH*100:.1f}%)")
        lines.append(f"자산구성: 부동산 {asset.get('real_estate') or 0:,.0f}원, 주식 {asset.get('stocks') or 0:,.0f}원, "
                      f"퇴직연금 {asset.get('pension') or 0:,.0f}원, 현금 {asset.get('cash') or 0:,.0f}원")

        cat_lines = []
        for cat, _, target in SPENDING_TARGETS:
            actual = category_actual_this_month(cat)
            if actual is not None:
                cat_lines.append(f"{cat} 목표{target:,.0f}/실적{actual:,.0f}")
        if cat_lines:
            lines.append("이번 달 소비(목표/실적): " + ", ".join(cat_lines))

        plan_items = (data.get("invest_plan") or {}).get("items") or []
        if plan_items:
            invest_lines = [f"{it['name']} 월목표{(it.get('monthly_target') or 0):,.0f}원" for it in plan_items]
            lines.append("월 적립식 투자 배분 목표: " + ", ".join(invest_lines))

        trend = data.get("stock_monthly_trend") or []
        if len(trend) >= 2:
            prev, cur = trend[-2], trend[-1]
            lines.append(
                f"주식 평가손익 추이: 전월 {prev.get('total_profit') or 0:,.0f}원(수익률 {prev.get('avg_return_pct') or 0:.1f}%) "
                f"→ 이번달 {cur.get('total_profit') or 0:,.0f}원(수익률 {cur.get('avg_return_pct') or 0:.1f}%)"
            )
        elif trend:
            cur = trend[-1]
            lines.append(f"주식 평가손익: {cur.get('total_profit') or 0:,.0f}원 (수익률 {cur.get('avg_return_pct') or 0:.1f}%)")

        if tickers:
            profitable = [t for t in tickers if t.get("profit") is not None]
            if profitable:
                top = sorted(profitable, key=lambda t: t["profit"], reverse=True)[:3]
                bottom = sorted(profitable, key=lambda t: t["profit"])[:3]
                lines.append("평가손익 상위 3: " + ", ".join(f"{t['name']} {t['profit']:+,.0f}원" for t in top))
                lines.append("평가손익 하위 3: " + ", ".join(f"{t['name']} {t['profit']:+,.0f}원" for t in bottom))

        return "\n".join(lines)

    insight_key = current_ym
    saved_insight = None
    if history_sheet_id:
        try:
            saved_insight = history_store.load_text_snapshot(_get_gc_client(), history_sheet_id, "monthly_insights", insight_key)
        except Exception:
            saved_insight = None

    with st.container(border=True):
        col_h, col_btn = st.columns([4, 1])
        with col_h:
            st.markdown(f"**💡 {current_ym} 이번 달 인사이트**")
            if saved_insight:
                st.caption("이번 달 생성된 코멘트예요 (저장돼서 계속 유지됩니다).")
            else:
                st.caption("버튼을 눌러 이번 달 데이터 기반 코멘트를 생성해보세요. (월 1회 생성 권장, 호출당 소액 과금)")
        with col_btn:
            btn_label = "🔄 다시 생성" if saved_insight else "✨ 생성하기"
            gen_clicked = st.button(btn_label, key="gen_monthly_insight")

        if gen_clicked:
            try:
                with st.spinner("이번 달 데이터를 분석하는 중..."):
                    data_text = _build_insight_data_text()
                    new_insight = ai_insights_module().generate_monthly_insight(anthropic_api_key, data_text)
                saved_insight = new_insight
                if history_sheet_id:
                    try:
                        history_store.save_text_snapshot(_get_gc_client(), history_sheet_id, "monthly_insights", insight_key, new_insight)
                    except Exception:
                        st.warning("생성은 됐지만 저장에는 실패했어요. 새로고침하면 사라질 수 있어요.")
                st.rerun()
            except Exception as e:
                st.error(f"인사이트 생성에 실패했어요: {e}")

        if saved_insight:
            st.markdown(saved_insight)
        elif not gen_clicked:
            st.caption("아직 이번 달 인사이트가 없어요.")

    st.divider()


def ai_insights_module():
    import ai_insights
    return ai_insights


def monthly_goal_chart(history: list[dict], value_key: str, goal: float, color: str, title: str):
    """월별 실적 막대 + 목표 기준선을 함께 보여주는 차트."""
    months = [h["year_month"] for h in history]
    values = [h.get(value_key) or 0 for h in history]

    fig = go.Figure()
    fig.add_bar(
        x=months, y=values, marker_color=color, name="실적",
        text=[f"{v:,.0f}원" for v in values], textposition="outside",
        textfont=dict(color="#e8ecf1", size=11),
        hovertemplate="%{x}: %{y:,.0f}원<extra></extra>",
    )
    fig.add_hline(
        y=goal, line=dict(color="#d4af37", width=2, dash="dash"),
        annotation_text=f"목표 {goal:,.0f}원", annotation_font_color="#d4af37",
        annotation_position="top left",
    )
    fig.update_layout(
        title=dict(text=title, font=dict(size=14, color="#e8ecf1")),
        height=260,
        paper_bgcolor="#12171f", plot_bgcolor="#12171f",
        font={"color": "#e8ecf1"},
        margin=dict(t=40, b=10, l=10, r=10),
        yaxis=dict(showticklabels=False, showgrid=False, zeroline=False, range=[0, max(goal, max(values, default=0)) * 1.15]),
        xaxis=dict(gridcolor="#232b36", type="category"),  # "2026-08" 같은 문자열을 날짜로 오인해서 이상한 눈금이 나오는 것 방지
        showlegend=False,
    )
    return fig


# ---------------------------------------------------------------------------
# 목표 진행 현황 (월별 추이)
# ---------------------------------------------------------------------------
c1, c2 = st.columns(2)
with c1:
    if networth_history:
        st.plotly_chart(
            monthly_goal_chart(networth_history, "net_worth", GOAL_NET_WORTH, "#34d8b0", "순자산 목표 진행률 (월별)"),
            width='stretch',
        )
    else:
        st.plotly_chart(gauge(net_worth, GOAL_NET_WORTH, "순자산 목표 진행률", "#34d8b0"), width='stretch')
        st.caption("기록용 시트를 연결하면 다음 달부터 월별 추이로 보여드려요.")
    gap = GOAL_NET_WORTH - net_worth
    st.metric("현재 순자산", eok(net_worth), delta=f"목표까지 {eok(gap)} 남음")
    if gap > 0:
        st.caption(f"필요 페이스: 월 {money(gap/months_left)}")

with c2:
    if networth_history:
        st.plotly_chart(
            monthly_goal_chart(networth_history, "cash", GOAL_CASH, "#ff6b6b", "현금 목표 진행률 (월별)"),
            width='stretch',
        )
    else:
        st.plotly_chart(gauge(cash, GOAL_CASH, "현금 목표 진행률", "#ff6b6b"), width='stretch')
        st.caption("기록용 시트를 연결하면 다음 달부터 월별 추이로 보여드려요.")
    gap_c = GOAL_CASH - cash
    st.metric("현재 현금", eok(cash), delta=f"목표까지 {eok(gap_c)} 남음")
    if gap_c > 0:
        st.caption(f"필요 페이스: 월 {money(gap_c/months_left)}")

if networth_history and len(networth_history) < 3:
    st.caption(f"📈 지금은 {len(networth_history)}개월치 기록만 있어요. 매달 앱을 열 때마다 자동으로 한 달씩 쌓입니다.")

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
        margin=dict(l=10, r=140, t=10, b=10),
        xaxis=dict(showticklabels=False, showgrid=False, zeroline=False, range=[0, max(vals) * 1.35]),
        yaxis=dict(tickfont=dict(size=13)),
        showlegend=False,
    )
    st.plotly_chart(fig, width='stretch')
else:
    st.info("자산 구성 데이터를 찾지 못했습니다.")

st.divider()

# ---------------------------------------------------------------------------
# 자산 계획 노트 (매달 5일 집행 예산/투자 배분 + 체크리스트)
# ---------------------------------------------------------------------------
st.subheader("자산 계획 노트")
st.caption("매월 5일, 전월 정산 후 아래 계획대로 이체합니다. 체크하면 자동으로 기록됩니다.")

# 월 적립식 투자 배분 - 자산현황 파일의 '자산배분' 탭에서 동적으로 가져옴 (하드코딩 아님)
_invest_plan = data.get("invest_plan") or {}
_invest_plan_items = _invest_plan.get("items") or []


def _split_name_note(raw_name: str):
    """'국내일반/미국직투 주식 (한투 64209401-21)' -> ('국내일반/미국직투 주식', '한투 64209401-21')"""
    m = re.match(r"^(.*?)\s*\((.+)\)\s*$", raw_name.strip())
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return raw_name.strip(), ""


if _invest_plan_items:
    INVEST_ITEMS = []
    for item in _invest_plan_items:
        title, note = _split_name_note(item["name"])
        monthly = item.get("monthly_target") or 0
        INVEST_ITEMS.append((title, monthly, note, item.get("annual_target")))
else:
    # 시트에서 못 읽어왔을 때의 폴백 (예전에 직접 입력해둔 계획)
    INVEST_ITEMS = [
        ("국내일반/미국주식or 현금(달러)", 3_500_000, "한투 64209401-21 · 지연 운용", None),
        ("지연 ISA", 1_350_000, "NH 20802815046 · 자동이체로 지수거래", None),
        ("수용 ISA", 1_350_000, "KB 37349932601 · 자동이체로 지수거래", None),
        ("수용 주택청약통장", 250_000, "우리 1073115374810 · 3년 후 다자녀 청약 도전", None),
        ("지연 연금저축", 500_000, "NH 20802814978 · 세제 혜택", None),
        ("IRP", 250_000, "계좌번호 미입력", None),
    ]
    st.warning(
        "자산현황 시트의 '자산배분' 탭을 찾지 못해서, 예전에 입력해둔 계획으로 대신 보여드려요. "
        "디버그 모드를 켜면 로그에서 확인할 수 있어요."
    )

if not history_sheet_id:
    st.info(
        "체크 상태를 저장하려면 '기록용 시트'가 필요해요. 지금은 체크해도 새로고침하면 사라져요. "
        "README '기록용 시트 만들기' 단계를 먼저 해주세요."
    )

if debug_mode:
    with st.expander("🔍 디버그: 자산배분 탭에서 읽어온 항목", expanded=False):
        if _invest_plan_items:
            st.dataframe(pd.DataFrame(_invest_plan_items)[["name", "annual_target", "monthly_target"]], width='stretch', hide_index=True)
        else:
            st.error("자산배분 표를 어느 탭에서도 못 찾았어요. 헤더에 '연간목표', '목표', '합계', '1월'이 모두 있는 행이 있는지 확인해주세요.")


invest_amounts_all = {}
invest_load_error = None
if history_sheet_id:
    try:
        invest_amounts_all = history_store.load_values(_get_gc_client(), history_sheet_id, "invest_amounts")
    except Exception as e:
        invest_load_error = str(e)

if invest_load_error:
    if "429" in invest_load_error or "Quota" in invest_load_error or "RESOURCE_EXHAUSTED" in invest_load_error:
        st.warning("투자 배분 기록을 불러오는 중 API 요청이 몰렸어요. 잠시 후 새로고침하면 다시 보일 거예요.")
    else:
        st.warning("투자 배분 기록을 불러오지 못했어요. 아래 항목은 이번 화면에서만 임시로 표시됩니다.")

this_month_invest = invest_amounts_all.get(current_ym, {})


def _save_invest_amount(item_key: str, amount_val: int):
    """저장 버튼 클릭 시 호출 - 명시적으로 값을 저장 (엔터 타이밍 문제 없이 확실하게)."""
    if not history_sheet_id:
        return False
    try:
        gc = _get_gc_client()
        history_store.upsert_value(gc, history_sheet_id, "invest_amounts", current_ym, item_key, str(amount_val))
        return True
    except Exception:
        return False


# --- 이번 달 지출 목표 (소비관리 탭 카테고리와 동일 기준) ---
st.markdown(
    "<div style='font-size:13px;font-weight:600;margin-top:10px;margin-bottom:10px;'>① 이번 달 지출 목표</div>",
    unsafe_allow_html=True,
)
budget_cols = st.columns(4)
for i, (cat, desc, target) in enumerate(SPENDING_TARGETS):
    actual = category_actual_this_month(cat)
    if actual is not None:
        over = actual > target
        actual_color = "#ff6b6b" if over else "#34d8b0"
        actual_html = (
            f'<div style="font-size:12px;color:{actual_color};margin-top:2px;">'
            f'실적 {actual:,.0f}원 ({actual/target*100:.0f}%)</div>'
        )
    else:
        actual_html = '<div style="font-size:11px;color:#8a94a6;margin-top:2px;">실적 데이터 없음</div>'
    with budget_cols[i % 4]:
        st.markdown(
            f"""
            <div style="background:#161c26;border:1px solid #232b36;border-radius:10px;
                        padding:10px 12px;margin-bottom:10px;min-height:96px;">
              <div style="font-size:12.5px;font-weight:600;color:#e8ecf1;">{cat}</div>
              <div style="font-size:10.5px;color:#8a94a6;margin-bottom:6px;line-height:1.3;">{desc}</div>
              <div style="font-size:14px;font-weight:600;color:#5b9dff;font-family:'IBM Plex Mono',monospace;">
                목표 {target:,.0f}원
              </div>
              {actual_html}
            </div>
            """,
            unsafe_allow_html=True,
        )

expected_income = 11_000_000
expected_saving = expected_income - SPENDING_TARGET_TOTAL
st.markdown(
    f"<div style='font-size:12px;color:#8a94a6;margin:2px 0 4px;'>"
    f"지출 목표 합계 <b style='color:#e8ecf1;'>{SPENDING_TARGET_TOTAL:,.0f}원</b> · "
    f"예상 수입 {expected_income:,.0f}원 − 지출목표 {SPENDING_TARGET_TOTAL:,.0f}원 "
    f"= 저축·투자 가능액 약 <b style='color:#34d8b0;'>{expected_saving:,.0f}원</b>"
    f"</div>",
    unsafe_allow_html=True,
)
st.caption(
    "실적은 자산현황 시트의 소비관리 탭, 이번 달(현재 월) 칸을 그대로 가져온 값이에요."
)

st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)

# --- 월 적립식 투자 배분 (카드형 UI) ---
st.markdown(
    "<div style='font-size:13px;font-weight:600;margin-bottom:10px;'>② 월 적립식 투자 배분 (2027년 12월까지 목표)</div>",
    unsafe_allow_html=True,
)

total_months = history_store.months_between_inclusive(current_ym, PLAN_DEADLINE)
total_invest = sum(a for _, a, _, _ in INVEST_ITEMS)

# --- 이번 달 실행률: 실제 이체금액 합계 / 목표 합계 ---
this_month_actual_total = 0
for name, amount, note, annual_target in INVEST_ITEMS:
    item_key = f"투자_{name}"
    v = to_number(this_month_invest.get(item_key))
    this_month_actual_total += v or 0

exec_pct = (this_month_actual_total / total_invest * 100) if total_invest else 0
exec_color = "#34d8b0" if exec_pct >= 100 else ("#d4af37" if exec_pct >= 50 else "#ff6b6b")
st.markdown(
    f"""
    <div style="background:#161c26;border:1px solid #232b36;border-radius:10px;
                padding:14px 18px;margin-bottom:14px;">
      <div style="display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap;gap:6px;">
        <div style="font-size:13px;color:#8a94a6;">{current_ym} 이번 달 실행률</div>
        <div style="font-size:20px;font-weight:700;color:{exec_color};font-family:'IBM Plex Mono',monospace;">
          {this_month_actual_total:,.0f}원 / {total_invest:,.0f}원 <span style="font-size:14px;">({exec_pct:.0f}%)</span>
        </div>
      </div>
      <div style="background:#232b36;border-radius:6px;height:8px;overflow:hidden;margin-top:8px;">
        <div style="background:{exec_color};width:{min(exec_pct,100):.1f}%;height:100%;"></div>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

for name, amount, note, annual_target in INVEST_ITEMS:
    item_key = f"투자_{name}"

    # 지난 기록들에서 이 항목에 실제로 입력된 금액을 전부 더함 (고정금액이 아니라 직접 쓴 값 기준)
    recorded_amounts = []
    for ym, items in invest_amounts_all.items():
        raw = items.get(item_key)
        v = to_number(raw)
        if v:
            recorded_amounts.append(v)
    actual_total = sum(recorded_amounts)
    months_recorded = len(recorded_amounts)
    target_total = amount * total_months
    progress = min(actual_total / target_total, 1.0) if target_total else 0.0

    default_amount = to_number(this_month_invest.get(item_key))
    if default_amount is None:
        default_amount = 0
    is_done = default_amount > 0

    annual_note = f" · 1년 목표 {annual_target:,.0f}원" if annual_target else ""

    with st.container(border=True):
        c1, c2 = st.columns([3, 1.3])
        with c1:
            st.markdown(
                f"""
                <div style="font-size:15px;font-weight:700;color:#e8ecf1;margin-bottom:6px;">{name}</div>
                <div style="font-size:11.5px;color:#5b9dff;margin-bottom:10px;">{note}</div>
                <div style="font-size:11px;color:#8a94a6;">월 목표 {amount:,.0f}원{annual_note}</div>
                """,
                unsafe_allow_html=True,
            )
        with c2:
            text_key = f"txt_{item_key}_{current_ym}"
            if text_key not in st.session_state:
                st.session_state[text_key] = f"{int(default_amount):,}"

            col_in, col_btn = st.columns([2.2, 1])
            with col_in:
                st.text_input(
                    "이번 달 실제 이체액 (원)",
                    key=text_key,
                    disabled=not history_sheet_id,
                    help="숫자만 입력하세요 (콤마는 자동으로 붙어요). 다 쓰신 뒤 오른쪽 '저장' 버튼을 눌러주세요 — 엔터로는 저장되지 않아요.",
                )
            with col_btn:
                st.markdown("<div style='height:28px;'></div>", unsafe_allow_html=True)  # 라벨 높이만큼 버튼 위치 맞추기
                if st.button("저장", key=f"save_{item_key}_{current_ym}", disabled=not history_sheet_id, width='stretch'):
                    digits = re.sub(r"[^\d]", "", st.session_state[text_key] or "")
                    amount_val = int(digits) if digits else 0
                    ok = _save_invest_amount(item_key, amount_val)
                    if ok:
                        st.session_state[text_key] = f"{amount_val:,}"
                        st.toast(f"{name} 저장 완료: {amount_val:,}원", icon="✅")
                        st.rerun()
                    else:
                        st.toast("⚠️ 저장에 실패했어요. 잠시 후 다시 시도해주세요.", icon="⚠️")

        bar_color = "#34d8b0" if is_done else "#5b9dff"
        st.markdown(
            f"""
            <div style="margin-top:2px;">
              <div style="display:flex;justify-content:space-between;font-size:11px;color:#8a94a6;margin-bottom:4px;">
                <span>누적 {months_recorded}개월 입력 · 합계 {actual_total:,.0f}원</span>
                <span>2027.12 목표 {target_total:,.0f}원 · {progress*100:.0f}%</span>
              </div>
              <div style="background:#232b36;border-radius:6px;height:8px;overflow:hidden;">
                <div style="background:{bar_color};width:{progress*100:.1f}%;height:100%;"></div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

_saving_pct = (total_invest / expected_saving * 100) if expected_saving else 0
st.markdown(
    f"<div style='font-size:12px;color:#8a94a6;margin-top:10px;'>"
    f"월 투자 배분 합계 <b style='color:#e8ecf1;'>{total_invest:,.0f}원</b> "
    f"(계획 저축가능액 대비 {_saving_pct:.0f}%) · 남은 개월수(당월 포함) {total_months}개월"
    f"</div>",
    unsafe_allow_html=True,
)

with st.expander("📋 소비관리 탭에 직접 붙여넣을 '목표' 수식 (선택)"):
    st.caption(
        "서비스 계정은 자산현황 시트에 '읽기' 권한만 있어서, 저희가 직접 시트에 써넣을 수는 없어요. "
        "대신 아래 값을 소비관리 탭에 '목표' 행으로 직접 추가해서 붙여넣으시면, "
        "26.08~27.12까지 매달 같은 목표가 채워집니다 (지출 목표는 매달 고정이라 전부 같은 값이에요)."
    )
    target_row = "목표\t" + "\t".join(f"{t:,.0f}" for _, _, t in SPENDING_TARGETS)
    st.code(target_row, language=None)
    st.caption("이 줄을 복사해서 카테고리 행들(Eat/Live/…) 아래에 새 행으로 붙여넣고, 오른쪽으로 월별 칸까지 드래그해서 채우면 돼요.")

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
liability_items = asset.get("liability_items", {})
asset_prev = data.get("asset_prev_items", {})

if asset_items:
    rows = []
    for name, cur_val in asset_items.items():
        prev_val = asset_prev.get(name)
        delta = (cur_val - prev_val) if (prev_val is not None) else None
        rows.append(
            {
                "구분": "자산",
                "항목": name,
                "이번 달": cur_val,
                "지난달": prev_val if prev_val is not None else None,
                "증감": delta,
            }
        )

    total_asset_cur = sum(r["이번 달"] for r in rows)
    total_asset_prev_vals = [r["지난달"] for r in rows if r["지난달"] is not None]
    total_asset_prev = sum(total_asset_prev_vals) if len(total_asset_prev_vals) == len(rows) else None
    rows.append(
        {
            "구분": "자산",
            "항목": "자산 합계",
            "이번 달": total_asset_cur,
            "지난달": total_asset_prev,
            "증감": (total_asset_cur - total_asset_prev) if total_asset_prev is not None else None,
        }
    )

    total_liability_cur = 0
    total_liability_prev = None
    if liability_items:
        liab_prev_vals = []
        for name, cur_val in liability_items.items():
            prev_val = asset_prev.get(name)
            delta = (cur_val - prev_val) if (prev_val is not None) else None
            rows.append(
                {
                    "구분": "부채",
                    "항목": name,
                    "이번 달": -cur_val,
                    "지난달": (-prev_val if prev_val is not None else None),
                    "증감": (-delta if delta is not None else None),
                }
            )
            total_liability_cur += cur_val
            liab_prev_vals.append(prev_val)
        total_liability_prev = sum(liab_prev_vals) if all(v is not None for v in liab_prev_vals) else None
        rows.append(
            {
                "구분": "부채",
                "항목": "부채 합계",
                "이번 달": -total_liability_cur,
                "지난달": (-total_liability_prev if total_liability_prev is not None else None),
                "증감": (-(total_liability_cur - total_liability_prev) if total_liability_prev is not None else None),
            }
        )
    else:
        # 부채 상세 항목을 못 찾았으면, asset 요약에 있는 부채 총액이라도 사용
        fallback_debt = asset.get("total_debt")
        if fallback_debt:
            total_liability_cur = fallback_debt
            rows.append(
                {"구분": "부채", "항목": "부채 합계", "이번 달": -fallback_debt, "지난달": None, "증감": None}
            )

    net_worth_cur = total_asset_cur - total_liability_cur
    net_worth_prev = (
        (total_asset_prev - total_liability_prev)
        if (total_asset_prev is not None and total_liability_prev is not None)
        else None
    )
    rows.append(
        {
            "구분": "순자산",
            "항목": "순자산 (자산 − 부채)",
            "이번 달": net_worth_cur,
            "지난달": net_worth_prev,
            "증감": (net_worth_cur - net_worth_prev) if net_worth_prev is not None else None,
        }
    )

    df_assets = pd.DataFrame(rows)

    def _highlight_total(row):
        if row["항목"] == "순자산 (자산 − 부채)":
            return ["font-weight: bold; border-top: 3px double #d4af37; color:#d4af37;" for _ in row]
        if row["항목"] in ("자산 합계", "부채 합계"):
            return ["font-weight: bold; border-top: 2px solid #8a94a6" for _ in row]
        return ["" for _ in row]

    st.dataframe(
        df_assets.drop(columns=["구분"]).style.apply(_highlight_total, axis=1).format(
            {"이번 달": "{:+,.0f}원", "지난달": "{:+,.0f}원", "증감": "{:+,.0f}원"},
            na_rep="—",
        ),
        width='stretch',
        hide_index=True,
        height=(len(rows) + 1) * 36 + 4,  # 행 개수에 딱 맞춰서 - 내부 스크롤 없이 순자산까지 한 번에 보이도록
    )
    if not liability_items and not asset.get("total_debt"):
        st.caption("⚠️ 부채 항목을 찾지 못해서 순자산에 부채가 반영되지 않았을 수 있어요. 디버그 모드로 확인해보세요.")
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
        xaxis=dict(gridcolor="#232b36", type="category"),
    )
    st.plotly_chart(fig, width='stretch')

    filled_income = [m for m in ledger if m["income"]]
    if len(filled_income) < len(ledger) / 2:
        st.warning(
            "가계부에 수입이 입력된 달이 적어서(전체 중 일부만) 실제 저축여력을 "
            "정확히 계산할 수 없습니다. 매달 수입을 입력하면 이 비교가 더 정확해집니다."
        )
else:
    st.info("가계부 데이터를 찾지 못했습니다. 디버그 모드를 켜고 fetch_data.py의 라벨 검색 로직을 확인하세요.")

# --- 최근 6개월 고정지출 (가계부 시트, 각 월 탭의 '고정지출' 셀 값을 그대로 가져옴) ---
st.markdown("<div style='font-size:13px;font-weight:600;margin-top:16px;margin-bottom:8px;'>최근 6개월 고정지출</div>", unsafe_allow_html=True)

if debug_mode:
    with st.expander("🔍 디버그: 가계부 원본 데이터 (월별 income/expense/fixed_expense)", expanded=True):
        if ledger:
            st.dataframe(pd.DataFrame(ledger), width='stretch', hide_index=True)
            n_missing = sum(1 for m in ledger if m.get("fixed_expense") is None)
            if n_missing:
                st.warning(f"fixed_expense가 비어있는 달이 {n_missing}개 있어요. 위 표에서 None으로 표시된 행이에요.")
            else:
                st.success("모든 달에서 fixed_expense를 정상적으로 찾았어요.")
        else:
            st.error("ledger 데이터 자체가 비어있어요 (가계부 시트 연결/파싱 문제일 수 있어요).")

fixed_expense_entries = [m for m in ledger if m.get("fixed_expense") is not None]

if fixed_expense_entries:
    recent = fixed_expense_entries[-6:]  # 이미 날짜순 정렬되어 있음 (ledger가 date로 정렬됨)
    recent_months_labels = [m["date"] for m in recent]
    fixed_totals = [m["fixed_expense"] for m in recent]

    fig = go.Figure(
        go.Bar(
            x=recent_months_labels, y=fixed_totals,
            marker_color="#a78bfa",
            text=[f"{v:,.0f}원" for v in fixed_totals],
            textposition="outside",
            textfont=dict(color="#e8ecf1", size=11),
            hovertemplate="%{x}: %{y:,.0f}원<extra></extra>",
        )
    )
    avg_fixed = sum(fixed_totals) / len(fixed_totals) if fixed_totals else 0
    fig.add_hline(
        y=avg_fixed, line=dict(color="#8a94a6", width=1.5, dash="dot"),
        annotation_text=f"평균 {avg_fixed:,.0f}원", annotation_font_color="#8a94a6",
    )
    fig.update_layout(
        height=280,
        paper_bgcolor="#12171f", plot_bgcolor="#12171f",
        font={"color": "#e8ecf1"},
        margin=dict(t=20, b=10, l=10, r=10),
        yaxis=dict(showticklabels=False, showgrid=False, zeroline=False, range=[0, max(fixed_totals) * 1.2]),
        xaxis=dict(gridcolor="#232b36", type="category"),
        showlegend=False,
    )
    st.plotly_chart(fig, width='stretch')
    st.caption(f"가계부 시트 각 월 탭의 '고정지출' 셀 값을 그대로 가져온 최근 {len(recent)}개월 추이예요.")
else:
    st.info(
        "가계부 시트에서 '고정지출' 값을 찾지 못했어요. 각 월 탭에 '고정지출'이라는 라벨이 있는지, "
        "혹은 F80 셀에 값이 있는지 확인해주세요. 디버그 모드를 켜면 로그에서 확인할 수 있어요."
    )

st.divider()

# ---------------------------------------------------------------------------
# 소비관리 (카테고리별 월간 지출) - 자산현황 파일의 '소비관리' 탭
# ---------------------------------------------------------------------------
st.subheader("소비관리 · 카테고리별 지출")

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
        xaxis=dict(gridcolor="#232b36", type="category"),
    )
    st.plotly_chart(fig, width='stretch')
    st.caption("Eat·Live·Wear·Enjoy·Edu·Ride·Other 카테고리별 지출을 월별로 쌓아서 보여줘요.")

    # --- 이번 달 실적 vs 목표(자산 계획 노트에서 정한 값) 비교 ---
    st.markdown("<div style='font-size:13px;font-weight:600;margin-top:14px;margin-bottom:8px;'>이번 달 목표 대비 실적</div>", unsafe_allow_html=True)
    target_map = {cat: target for cat, _, target in SPENDING_TARGETS}
    this_month_label = sp_months[_current_month_idx] if _current_month_idx < len(sp_months) else None
    compare_rows = []
    for cat, monthly_vals in sp_categories.items():
        actual = monthly_vals[_current_month_idx] if _current_month_idx < len(monthly_vals) else 0
        target = target_map.get(cat)
        if target:
            diff = actual - target
            compare_rows.append({"카테고리": cat, "목표": target, "실적": actual, "차이": diff, "달성률": actual / target * 100})
    if compare_rows:
        df_cmp = pd.DataFrame(compare_rows)

        def _over_budget(row):
            color = "#ff6b6b" if row["차이"] > 0 else "#34d8b0"
            return ["", "", "", f"color:{color};font-weight:600;", f"color:{color};"]

        st.dataframe(
            df_cmp.style.apply(_over_budget, axis=1).format(
                {"목표": "{:,.0f}원", "실적": "{:,.0f}원", "차이": "{:+,.0f}원", "달성률": "{:.0f}%"}
            ),
            width='stretch',
            hide_index=True,
        )
        st.caption(f"기준: {this_month_label or '이번 달'} 실적 (빨강=목표 초과, 초록=목표 이내)")
else:
    st.info(
        "소비관리 탭이 아직 비어있어요. 시트에 카테고리별 지출이 채워지면 "
        "이 자리에 자동으로 그래프와 목표 대비 실적이 나타납니다 (코드 수정 필요 없음)."
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
    st.plotly_chart(fig, width='stretch')

    if not history_sheet_id:
        st.caption("3개월/6개월 전 값을 보려면 기록용 시트를 연결해야 해요 (README '기록용 시트 만들기' 참고).")
    elif not stock_trend.get("3m_ago") and not stock_trend.get("6m_ago"):
        st.caption("아직 3개월/6개월 치 기록이 쌓이지 않았어요. 계속 사용하시면 자동으로 채워집니다.")

# --- 월별 평균 수익률 vs 평가손익 흐름 (이중 그래프) ---
st.markdown("<div style='font-size:13px;font-weight:600;margin-top:18px;margin-bottom:6px;'>월별 평균 수익률 vs 평가손익 흐름</div>", unsafe_allow_html=True)
stock_monthly_trend = data.get("stock_monthly_trend") or []

if len(stock_monthly_trend) >= 2:
    months_t = [p["year_month"] for p in stock_monthly_trend]
    avg_returns = [p["avg_return_pct"] for p in stock_monthly_trend]
    total_profits = [p["total_profit"] for p in stock_monthly_trend]

    fig = go.Figure()
    fig.add_bar(
        x=months_t, y=total_profits, name="평가손익",
        marker_color="#5b9dff", yaxis="y",
        hovertemplate="평가손익 %{y:,.0f}원<extra></extra>",
    )
    fig.add_trace(
        go.Scatter(
            x=months_t, y=avg_returns, name="평균 수익률",
            mode="lines+markers", line=dict(color="#d4af37", width=3), marker=dict(size=7),
            yaxis="y2",
            hovertemplate="평균 수익률 %{y:.1f}%<extra></extra>",
        )
    )
    fig.update_layout(
        height=320,
        paper_bgcolor="#12171f", plot_bgcolor="#12171f",
        font={"color": "#e8ecf1"},
        legend=dict(orientation="h", y=1.12),
        margin=dict(t=40, b=10),
        yaxis=dict(title="평가손익(원)", gridcolor="#232b36", tickfont=dict(color="#8a94a6")),
        yaxis2=dict(title="평균 수익률(%)", overlaying="y", side="right", showgrid=False),
        xaxis=dict(gridcolor="#232b36", type="category"),
    )
    st.plotly_chart(fig, width='stretch')
    st.caption(
        "파란 막대(평가손익)는 계속 쌓이는 게 중요하고, 금색 선(평균 수익률)은 적립식 매수 특성상 낮아져도 자연스러워요 — "
        "수익률보다 평가손익의 우상향 흐름에 집중하시면 돼요."
    )
elif not history_sheet_id:
    st.info("기록용 시트를 연결하면 다음 달부터 월별 흐름이 쌓여요.")
else:
    st.info(f"아직 {len(stock_monthly_trend)}개월치 기록만 있어요. 다음 달부터 그래프가 그려집니다.")

# --- 국내/미국 TOP5 평가손익 ---
st.markdown("<div style='font-size:13px;font-weight:600;margin-top:18px;margin-bottom:6px;'>시장별 TOP5 평가손익</div>", unsafe_allow_html=True)
if tickers:
    top5_markets = sorted(set(t["market"] for t in tickers))
    top5_cols = st.columns(len(top5_markets))
    for col, mk in zip(top5_cols, top5_markets):
        with col:
            mk_tickers = [t for t in tickers if t["market"] == mk and t.get("profit") is not None]
            top5 = sorted(mk_tickers, key=lambda t: t["profit"], reverse=True)[:5]
            if top5:
                # 리스트 순서 그대로(1등이 맨 앞) 넣고, 축을 반전시켜서 1등이 위로 오게 함
                # (수동으로 리스트를 뒤집으면 순서가 꼬이기 쉬워서, 축 반전이 더 안전합니다)
                # 계좌가 여러 개면 같은 종목명이 겹쳐서 막대가 포개지므로, 계좌명을 같이 표시해서 구분
                name_counts = {}
                for t in mk_tickers:
                    name_counts[t["name"]] = name_counts.get(t["name"], 0) + 1
                names = [
                    f"{t['name']} ({t['account']})" if name_counts.get(t["name"], 0) > 1 and t.get("account") else t["name"]
                    for t in top5
                ]
                profits = [t["profit"] for t in top5]
                colors_top5 = ["#34d8b0" if p >= 0 else "#ff6b6b" for p in profits]

                max_abs = max(abs(p) for p in profits)
                min_p = min(0, min(profits))
                max_p = max(profits)
                pad = max_abs * 0.45  # 데이터 라벨이 잘리지 않도록 오른쪽에 여유 공간 확보

                fig = go.Figure(
                    go.Bar(
                        x=profits, y=names, orientation="h",
                        marker_color=colors_top5,
                        text=[f"{p:+,.0f}원" for p in profits],
                        textposition="outside",
                        textfont=dict(color="#e8ecf1", size=11),
                        hovertemplate="%{y}: %{x:+,.0f}원<extra></extra>",
                    )
                )
                fig.update_layout(
                    title=dict(text=f"{mk} TOP5", font=dict(size=13, color="#e8ecf1")),
                    height=60 + 42 * len(top5),
                    paper_bgcolor="#12171f", plot_bgcolor="#12171f",
                    font={"color": "#e8ecf1"},
                    margin=dict(l=10, r=90, t=40, b=10),
                    xaxis=dict(
                        showticklabels=False, showgrid=False, zeroline=True, zerolinecolor="#8a94a6",
                        range=[min_p - pad * 0.15, max_p + pad],
                    ),
                    yaxis=dict(tickfont=dict(size=12), autorange="reversed"),  # 1등이 맨 위로
                    showlegend=False,
                )
                st.plotly_chart(fig, width='stretch')
                if len(mk_tickers) < 5:
                    st.caption(f"평가손익 값이 있는 {mk} 종목이 {len(mk_tickers)}개뿐이라 {len(top5)}개만 표시돼요.")
            else:
                st.caption(f"{mk} 데이터 없음")
else:
    st.info("종목 데이터가 없어서 TOP5를 만들 수 없습니다.")

st.divider()

# ---------------------------------------------------------------------------
# 주식 종목별 상세 (전월 대비)
# ---------------------------------------------------------------------------
st.subheader("주식 종목별 현황")

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

                # 이 시장(예: 미국)의 모든 계좌 칸이 비어있으면 '계좌' 열 자체를 숨김
                if df_t["계좌"].fillna("").eq("").all():
                    df_t = df_t.drop(columns=["계좌"])

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
                    width='stretch',
                    hide_index=True,
                    height=(len(df_t) + 1) * 36 + 4,  # 종목 개수만큼 높이를 늘려서 내부 스크롤 없이 한 번에 보이도록
                )
    if not ticker_prev:
        st.caption("아직 지난달 기록이 없어서 증감이 비어있어요. 다음 달부터 채워집니다.")
else:
    st.info("종목별 데이터를 찾지 못했습니다. 디버그 모드를 켜고 로그를 확인해주세요.")

st.divider()

# ---------------------------------------------------------------------------
# 매수/보류/매도 판단 (60일·120일 이평선 + 시트 수익률, 야후 파이낸스 연동)
# ---------------------------------------------------------------------------
st.subheader("종목별 매수 · 보류 · 매도 판단")
st.caption(
    "⚠️ 투자 조언이 아니라 아래 규칙에 따른 단순 계산 결과입니다. "
    "매수: 목표비중 미달 + 60일·120일 이평선 모두 이하 (둘 다) · "
    "매도: 수익률(시트) -30% 이하 AND 목표비중 1.5배 초과 (둘 다) · 나머지는 보류"
)

if tickers:
    @st.cache_data(ttl=6 * 60 * 60)  # 6시간 캐시 - 야후 파이낸스 호출을 너무 자주 하지 않도록
    def _load_market_data(market: str, code: str):
        import market_data
        return market_data.fetch_technical_and_fundamental(market, code)

    @st.cache_data(ttl=6 * 60 * 60)
    def _load_usd_krw_rate():
        import market_data
        return market_data.fetch_usd_krw_rate()

    import market_data

    usd_krw_rate = _load_usd_krw_rate()

    signal_tabs = st.tabs(markets)
    for tab, market in zip(signal_tabs, markets):
        with tab:
            is_domestic = "국내" in market
            # 국내가 아닌(=해외) 종목은 이동평균선이 달러 기준이라, 평단가/실시간가도 달러로 맞춰야
            # 서로 비교(매수/매도 판단)가 맞고, 표에서도 단위가 안 헷갈려요.
            use_usd = not is_domestic
            if use_usd and not usd_krw_rate:
                st.warning("환율 정보를 못 가져와서, 이 탭은 원화 기준으로 대신 표시합니다.")
                use_usd = False

            with st.spinner(f"{market} 종목의 시세 데이터를 불러오는 중..."):
                sig_rows = []
                reasons_map = {}
                yf_failures = 0
                for t in tickers:
                    if t["market"] != market:
                        continue

                    # 1) 시트에서 온 값은 항상 먼저 채워둠 - 야후 파이낸스가 실패해도 이 값들은 안전.
                    avg_buy = t.get("avg_buy_price")
                    cur_price = t.get("price")
                    sheet_return_pct = t.get("return_pct")  # 실시간 계산 대신 시트에 이미 있는 수익률 그대로 사용
                    if use_usd and usd_krw_rate:
                        try:
                            avg_buy = (avg_buy / usd_krw_rate) if avg_buy is not None else None
                            cur_price = (cur_price / usd_krw_rate) if cur_price is not None else None
                        except Exception:
                            pass  # 변환 실패해도 원래 값 유지

                    # 2) 야후 파이낸스 조회 - 실패해도 아래 값들만 비고, 위 시트값엔 영향 없음.
                    md = {}
                    try:
                        loaded = _load_market_data(t["market"], t["code"])
                        if isinstance(loaded, dict):
                            md = loaded
                    except Exception as e:
                        yf_failures += 1
                        reasons_map[t.get("name", "")] = [f"시세 데이터 조회 실패: {e}"]

                    # 3) 판단 계산 - 이것도 별도로 감싸서, 실패해도 위 값들은 표에 그대로 남음.
                    try:
                        result = market_data.classify_signal(
                            sheet_return_pct, cur_price, md.get("ma60"), md.get("ma120"),
                            target_weight_pct=t.get("target_weight_pct"),
                            current_weight_pct=t.get("current_weight_pct"),
                        )
                    except Exception as e:
                        result = {"signal": "—", "reasons": [f"판단 계산 오류: {e}"]}

                    if t.get("name") not in reasons_map:
                        reasons_map[t.get("name", "")] = result["reasons"]

                    sig_rows.append({
                        "종목명": t.get("name", ""),
                        "계좌": t.get("account", ""),
                        "구매평단가": avg_buy,
                        "실시간평단가": cur_price,
                        "수익률": sheet_return_pct,
                        "60일 이평선": md.get("ma60"),
                        "120일 이평선": md.get("ma120"),
                        "목표비중": t.get("target_weight_pct"),
                        "현재비중": t.get("current_weight_pct"),
                        "판단": result["signal"],
                    })

                if yf_failures and yf_failures == len(sig_rows) and sig_rows:
                    st.warning(
                        "⚠️ 이 탭의 모든 종목에서 야후 파이낸스 시세 조회에 실패했어요. "
                        "이평선만 비어있고, 구매평단가·수익률·비중 등 시트 값은 정상입니다. "
                        "Streamlit Cloud에서 야후 파이낸스 접속이 일시적으로 막힌 경우가 많아요 — 잠시 후 새로고침해보세요."
                    )

            if sig_rows:
                df_sig = pd.DataFrame(sig_rows)

                if df_sig["계좌"].fillna("").eq("").all():
                    df_sig = df_sig.drop(columns=["계좌"])

                def _signal_color(row):
                    colors = {
                        "매수 고려": "color:#34d8b0;font-weight:600;",
                        "매도 고려": "color:#ff6b6b;font-weight:600;",
                        "보류": "color:#d4af37;font-weight:600;",
                    }
                    styles = []
                    for col in row.index:
                        if col == "판단":
                            styles.append(colors.get(row["판단"], ""))
                        elif col == "수익률":
                            v = row["수익률"]
                            styles.append("color:#34d8b0;" if (v is not None and v >= 0) else ("color:#ff6b6b;" if v is not None else ""))
                        else:
                            styles.append("")
                    return styles

                price_fmt = "${:,.2f}" if use_usd else "{:,.0f}원"
                st.dataframe(
                    df_sig.style.apply(_signal_color, axis=1).format(
                        {
                            "구매평단가": price_fmt,
                            "실시간평단가": price_fmt,
                            "수익률": "{:+.1f}%",
                            "60일 이평선": price_fmt,
                            "120일 이평선": price_fmt,
                            "목표비중": "{:.1f}%",
                            "현재비중": "{:.1f}%",
                        },
                        na_rep="—",
                    ),
                    width='stretch',
                    hide_index=True,
                    height=(len(df_sig) + 1) * 36 + 4,  # 종목 개수만큼 높이를 늘려서 내부 스크롤 없이 한 번에 보이도록
                )
                with st.expander("종목별 판단 근거 보기"):
                    for name, reasons in reasons_map.items():
                        st.markdown(f"**{name}** — {' / '.join(reasons)}")
                if use_usd:
                    st.caption(f"이 탭은 전부 달러($) 기준이에요. (환율 1USD ≈ {usd_krw_rate:,.0f}원 적용)")
    st.caption(
        "60일/120일 이평선은 야후 파이낸스 무료 데이터라 비어있거나 다소 부정확할 수 있어요. "
        "수익률은 시트의 '수익률(%)' 값을 그대로 가져온 값이고, 목표비중은 시트의 '목표 비중' 열을 그대로 가져온 값이에요 (없으면 '—')."
    )
else:
    st.info("종목 데이터가 없어서 판단표를 만들 수 없습니다.")

st.caption("이 페이지는 열릴 때마다(최대 10분 캐시) 구글시트 최신 값을 다시 읽어옵니다.")
