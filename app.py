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

from fetch_data import fetch_all, get_client
from sheet_utils import to_number
import history_store

# ---------------------------------------------------------------------------
# 설정: 목표
# ---------------------------------------------------------------------------
GOAL_NET_WORTH = 1_000_000_000
GOAL_CASH = 100_000_000
DEADLINE = date(2027, 12, 31)

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
current_ym = data.get("year_month") or date.today().strftime("%Y-%m")

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
# 자산 계획 노트 (매달 5일 집행 예산/투자 배분 + 체크리스트)
# ---------------------------------------------------------------------------
st.subheader("자산 계획 노트")
st.caption("매월 5일, 전월 정산 후 아래 계획대로 이체합니다. 체크하면 자동으로 기록됩니다.")

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

INVEST_ITEMS = [
    ("국내일반/미장 주식", 3_500_000, "한투", "64209401-21", "지연 운용 · 월말 수용 보고"),
    ("지연 ISA", 1_350_000, "NH", "20802815046", "자동이체로 지수거래"),
    ("수용 ISA", 1_350_000, "KB", "37349932601", "자동이체로 지수거래"),
    ("수용 주택청약통장", 250_000, "우리", "1073115374810", "3년 후 다자녀 청약 도전"),
    ("지연 연금저축", 500_000, "NH", "20802814978", "세제 혜택"),
]

if not history_sheet_id:
    st.info(
        "체크 상태를 저장하려면 '기록용 시트'가 필요해요. 지금은 체크해도 새로고침하면 사라져요. "
        "README '기록용 시트 만들기' 단계를 먼저 해주세요."
    )


@st.cache_resource
def _get_gc_client():
    return get_client(json.loads(sa_info_json))


checklist_all = {}
checklist_load_error = None
if history_sheet_id:
    try:
        checklist_all = history_store.load_checklist(_get_gc_client(), history_sheet_id, "budget_checklist")
    except Exception as e:
        checklist_load_error = str(e)

if checklist_load_error:
    if "429" in checklist_load_error or "Quota" in checklist_load_error or "RESOURCE_EXHAUSTED" in checklist_load_error:
        st.warning("체크리스트를 불러오는 중 API 요청이 몰렸어요. 잠시 후 새로고침하면 다시 보일 거예요.")
    else:
        st.warning("체크리스트를 불러오지 못했어요. 아래 항목은 이번 화면에서만 임시로 표시됩니다.")

this_month_checks = checklist_all.get(current_ym, {})


def _on_toggle(item_key: str, widget_key: str):
    if not history_sheet_id:
        return
    try:
        gc = _get_gc_client()
        checked = st.session_state[widget_key]
        history_store.upsert_checklist_item(gc, history_sheet_id, "budget_checklist", current_ym, item_key, checked)
    except Exception:
        st.toast("⚠️ 체크 저장에 실패했어요. 잠시 후 다시 시도해주세요.", icon="⚠️")


# --- 이번 달 지출 목표 (소비관리 탭 카테고리와 동일 기준) ---
st.markdown(
    "<div style='font-size:13px;font-weight:600;margin-top:10px;margin-bottom:10px;'>① 이번 달 지출 목표</div>",
    unsafe_allow_html=True,
)
budget_cols = st.columns(4)
for i, (cat, desc, target) in enumerate(SPENDING_TARGETS):
    with budget_cols[i % 4]:
        st.markdown(
            f"""
            <div style="background:#161c26;border:1px solid #232b36;border-radius:10px;
                        padding:10px 12px;margin-bottom:10px;min-height:78px;">
              <div style="font-size:12.5px;font-weight:600;color:#e8ecf1;">{cat}</div>
              <div style="font-size:10.5px;color:#8a94a6;margin-bottom:6px;line-height:1.3;">{desc}</div>
              <div style="font-size:14px;font-weight:600;color:#5b9dff;font-family:'IBM Plex Mono',monospace;">
                {target:,.0f}원
              </div>
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
    "실제로 목표를 지켰는지는 아래 '소비관리 · 카테고리별 지출' 섹션에서 이번 달 실적과 자동으로 비교해서 보여줘요."
)

st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)

# --- 월 적립식 투자 배분 (카드형 UI) ---
st.markdown(
    "<div style='font-size:13px;font-weight:600;margin-bottom:10px;'>② 월 적립식 투자 배분 (2027년 12월까지 목표)</div>",
    unsafe_allow_html=True,
)

total_months = history_store.months_between_inclusive(current_ym, PLAN_DEADLINE)
total_invest = sum(a for _, a, _, _, _ in INVEST_ITEMS)

for name, amount, bank, acct_no, note in INVEST_ITEMS:
    item_key = f"투자_{name}"
    widget_key = f"chk_{item_key}_{current_ym}"

    checked_months = sum(1 for ym, items in checklist_all.items() if items.get(item_key))
    target_total = amount * total_months
    actual_total = amount * checked_months
    progress = min(actual_total / target_total, 1.0) if target_total else 0.0
    is_done = this_month_checks.get(item_key, False)

    with st.container(border=True):
        c1, c2 = st.columns([3, 1.1])
        with c1:
            st.markdown(
                f"""
                <div style="font-size:15px;font-weight:700;color:#e8ecf1;margin-bottom:4px;">{name}</div>
                <div style="display:flex;gap:6px;align-items:center;margin-bottom:8px;">
                  <span style="background:#232b36;color:#8a94a6;font-size:11px;padding:2px 8px;
                               border-radius:20px;font-family:'IBM Plex Mono',monospace;">{bank}</span>
                  <span style="color:#8a94a6;font-size:12px;font-family:'IBM Plex Mono',monospace;">{acct_no}</span>
                </div>
                <div style="font-size:11.5px;color:#5b9dff;margin-bottom:10px;">{note}</div>
                """,
                unsafe_allow_html=True,
            )
        with c2:
            st.markdown(
                f"""
                <div style="text-align:right;font-size:20px;font-weight:700;color:#e8ecf1;
                            font-family:'IBM Plex Mono',monospace;margin-bottom:6px;">
                  {amount/10000:,.0f}만원<span style="font-size:11px;color:#8a94a6;font-weight:400;">/월</span>
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.checkbox(
                "이번 달 이체 완료",
                value=is_done,
                key=widget_key,
                on_change=_on_toggle,
                args=(item_key, widget_key),
                disabled=not history_sheet_id,
            )

        bar_color = "#34d8b0" if is_done else "#5b9dff"
        st.markdown(
            f"""
            <div style="margin-top:2px;">
              <div style="display:flex;justify-content:space-between;font-size:11px;color:#8a94a6;margin-bottom:4px;">
                <span>누적 {checked_months}개월 · {actual_total:,.0f}원</span>
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
        use_container_width=True,
        hide_index=True,
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

    # --- 이번 달 실적 vs 목표(자산 계획 노트에서 정한 값) 비교 ---
    st.markdown("<div style='font-size:13px;font-weight:600;margin-top:14px;margin-bottom:8px;'>이번 달 목표 대비 실적</div>", unsafe_allow_html=True)
    target_map = {cat: target for cat, _, target in SPENDING_TARGETS}
    this_month_label = sp_months[-1] if sp_months else None
    compare_rows = []
    for cat, monthly_vals in sp_categories.items():
        actual = monthly_vals[-1] if monthly_vals else 0
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
            use_container_width=True,
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
                    use_container_width=True,
                    hide_index=True,
                )
    if not ticker_prev:
        st.caption("아직 지난달 기록이 없어서 증감이 비어있어요. 다음 달부터 채워집니다.")
else:
    st.info("종목별 데이터를 찾지 못했습니다. 디버그 모드를 켜고 로그를 확인해주세요.")

st.divider()

# ---------------------------------------------------------------------------
# 매수/보류/매도 판단 (60일·120일 이평선 + 3년 고점/저점, 야후 파이낸스 연동)
# ---------------------------------------------------------------------------
st.subheader("종목별 매수 · 보류 · 매도 판단")
st.caption(
    "⚠️ 투자 조언이 아니라 아래 규칙에 따른 단순 계산 결과입니다. "
    "매수: 목표비중 미달 + 120일 이평선 이하 + 3년 전저점 5% 이내 (3가지 전부) · "
    "매도: 수익률 -30% 이하 / 목표비중 1.5배 초과 / 3년 전고점 대비 -40% 급락 (하나라도) · 나머지는 보류"
)

all_sig_rows_for_ai = []  # AI 브리핑용 - tickers가 없으면 빈 채로 유지

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
                for t in tickers:
                    if t["market"] != market:
                        continue
                    md = _load_market_data(t["market"], t["code"])

                    avg_buy = t["avg_buy_price"]
                    cur_price = t["price"]
                    if use_usd and usd_krw_rate:
                        avg_buy = (avg_buy / usd_krw_rate) if avg_buy is not None else None
                        cur_price = (cur_price / usd_krw_rate) if cur_price is not None else None

                    result = market_data.classify_signal(
                        avg_buy, cur_price, md["ma120"],
                        three_year_low=md.get("three_year_low"),
                        three_year_high=md.get("three_year_high"),
                        target_weight_pct=t.get("target_weight_pct"),
                        current_weight_pct=t.get("current_weight_pct"),
                    )
                    reasons_map[t["name"]] = result["reasons"]
                    row = {
                        "종목명": t["name"],
                        "계좌": t["account"],
                        "구매평단가": avg_buy,
                        "실시간평단가": cur_price,
                        "실시간수익률": result.get("return_pct"),
                        "60일 이평선": md["ma60"],
                        "120일 이평선": md["ma120"],
                        "3년 전저점": md.get("three_year_low"),
                        "3년 전고점": md.get("three_year_high"),
                        "목표비중": t.get("target_weight_pct"),
                        "현재비중": t.get("current_weight_pct"),
                        "판단": result["signal"],
                    }
                    sig_rows.append(row)
                    all_sig_rows_for_ai.append({**row, "market": market})

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
                        elif col == "실시간수익률":
                            v = row["실시간수익률"]
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
                            "실시간수익률": "{:+.1f}%",
                            "60일 이평선": price_fmt,
                            "120일 이평선": price_fmt,
                            "3년 전저점": price_fmt,
                            "3년 전고점": price_fmt,
                            "목표비중": "{:.1f}%",
                            "현재비중": "{:.1f}%",
                        },
                        na_rep="—",
                    ),
                    use_container_width=True,
                    hide_index=True,
                )
                with st.expander("종목별 판단 근거 보기"):
                    for name, reasons in reasons_map.items():
                        st.markdown(f"**{name}** — {' / '.join(reasons)}")
                if use_usd:
                    st.caption(f"이 탭은 전부 달러($) 기준이에요. (환율 1USD ≈ {usd_krw_rate:,.0f}원 적용)")
    st.caption(
        "이평선·3년 고점/저점은 야후 파이낸스 무료 데이터라 비어있거나 다소 부정확할 수 있어요. "
        "목표비중은 주식 포트폴리오 시트의 '목표 비중' 열을 그대로 가져온 값이에요 (없으면 '—')."
    )
else:
    st.info("종목 데이터가 없어서 판단표를 만들 수 없습니다.")

st.divider()

# ---------------------------------------------------------------------------
# 오늘의 시장 브리핑 (정적 스냅샷 - 필요할 때 이 텍스트를 교체해서 갱신)
# ---------------------------------------------------------------------------
MARKET_BRIEFING_INTRO = """
**🇰🇷 국장 (전일 코스피/코스닥)**
- 8/20 기준 SK하이닉스 +12.73%, 삼성전자 +9.49% 급등 — 반도체 대형주 중심 강세
- 8/18에는 코스피가 장중 7,200을 회복했다가 매물 출회로 6,800선까지 반납하는 등 변동성이 커진 장세
- 최근 흐름: 반도체가 지수를 끌어올렸다 반납하는 롤러코스터 장세 지속 중

**🇺🇸 미장 (밤새 뉴욕증시)**
- 8/20(현지시간) 뉴욕 3대 지수 모두 상승 마감 — 나스닥 +0.16%(26,331.09), 다우 +0.22%(53,463.11), S&P500 +0.24%(7,710.70)
- 국채 금리 반등으로 상승폭이 줄어드는 흐름, 에너지 가격 상승에 따른 인플레이션 우려가 시장을 눌렀어요
- 전반적으로 "완만한 상승, 큰 모멘텀은 없는" 하루

**💡 국장 vs 미장 연결 포인트**
- 국장은 반도체 주도로 크게 출렁였는데, 미장은 상대적으로 잔잔했어요 → 삼성전자 포지션은 미국장보다 국내 수급(외국인·기관 동향)을 더 주시할 필요
- 미장은 금리·인플레이션 이슈로 상단이 막힌 분위기 → MSFT/META/GOOGL 등은 당분간 박스권 흐름 예상

---

**공포탐욕지수(Fear & Greed Index)** — 시장 전체 분위기가 겁먹었는지 흥분했는지를 0~100으로 보여주는 지표예요. 2026년 8월 19일 기준 **56점, '탐욕(Greed)' 구간**입니다.

| 구간 | 의미 |
|---|---|
| 0~25 (극도의 공포) | 다들 패닉 상태 → 저가 매수 최적기 |
| 26~45 (공포) | 다소 불안 → 우량주 저가 매수 시작 시점 |
| 46~55 (중립) | 방향성 탐색 중 |
| **56~75 (탐욕) ← 지금 여기** | 낙관 분위기 → 신규 진입 조심, 수익 실현 고민할 시점 |
| 76~100 (극도의 탐욕) | 광기 구간, 조정 위험 신호 |

지금은 "바겐세일" 타이밍이 아니라 "너무 오른 거 아닌가" 점검이 필요한 구간이에요. 다만 극단적 탐욕(76점 이상)은 아니라 당장 폭락 신호는 아니고, "완만한 경계" 정도로 보면 됩니다.

⚠️ RSI(개별 종목 과열도)·VIX(변동성 지수)는 실시간 조회가 안 되는 데이터라, 아래 코멘트는 시트의 수익률·전일 대비 등락 기준 모멘텀 추정치예요. 실제 매매 전엔 HTS/MTS에서 RSI를 직접 확인하세요.
"""

MARKET_BRIEFING_KR = """
**삼성전자 (005930)** — 일반계좌 35주 · +205% · 어제 +9.49%
반도체 업황은 좋지만 하루 +9%는 단기 과열 신호. 목표비중 15% 대비 12.26%로 여유는 있지만, 지금 더 사기보다 눌림목을 기다리는 게 안전. 일부 익절 고려.

**HD현대일렉트릭 (267260)** — 일반계좌 2주 · -29.59% · 어제 -0.80%
전력기기는 AI 데이터센터 테마로 주목받지만 낙폭이 큼. 반등 신호 확인 전엔 관망 권장.

**KB금융 (105560)** — 일반계좌 2주 · 0% · 어제 -3.85%
목표비중이 원래 작아(1%) 크게 신경 쓸 필요 없음. 관망 유지.

**현대차 (005380)** — 일반계좌 1주 · -24.09% · 어제 +0.85%
목표비중(3%) 대비 현재 2.17%로 매수 우선순위지만, 업종 부진 중이라 소액 분할매수 권장.

**TIGER 미국배당다우존스 (458730)** — ISA+연금저축 · +36.86% · 어제 +1.05%
탐욕 구간에서 상대적으로 안전한 배당형 ETF. 적립식 매수 지속 무방.

**RISE 미국 S&P500 (379780)** — ISA+연금저축 · +16~45%(계좌별) · 어제 +0.13%
개별종목 리스크 적은 대표지수 ETF. 꾸준히 유지.

**RISE 미국나스닥100 (368590)** — ISA+연금저축+퇴직연금 · +14~49%(계좌별) · 어제 +0.23%
퇴직연금 내 67.34% 비중으로 핵심 자산. 장기 보유는 괜찮지만 신규 자금 집중은 잠시 자제.

**TIGER 미국 S&P500 (360750)** — ISA+퇴직연금 · +32.57%/-2.38% · 매수시점 상이
퇴직연금 내 21.10% 비중 핵심 종목. 장기 적립 관점에서 유지.

**KODEX TRF5050 (329660)** — ISA 5주 · +23.67% · 거의 변동 없음
주식·채권 5:5 방어형 상품. 비중 작으니 유지.

**키움증권 (039490)** — ISA 5주 · -38.01% · 어제 +3.77%
증시 거래대금 증가로 반등 시작 신호. 반등세 지속되면 저가 매수 후보, 손실폭 크니 소액 신중 접근.

**네이버 (035420)** — ISA 6주 · +19.55% · 어제 +5.53%
AI 파트너십 뉴스로 강세. 목표비중(3%) 대비 4.34%로 초과 상태 — 관망 또는 일부 수익 실현 고려.

**기업은행 (024110)** — ISA 77주 · +46.73% · 어제 -1.72%
배당주 성격, 꾸준한 종목. 유지.

**SK텔레콤 (017670)** — ISA 13주 · +88.90%(최고 수익률) · 어제 -1.43%
목표비중(3%)에 근접, 일부 익절도 합리적 선택.
"""

MARKET_BRIEFING_US = """
**GOOGL (구글)** — 6주 · +39.50% · 어제 -1.17%
목표비중(8%) 대비 5.73%로 부족. 버핏도 최근 크게 늘린 종목 — 분할 매수 우선순위.

**QQQM (나스닥100 ETF)** — 12주 · +31.62% · 어제 -0.70%
목표비중(20%) 대비 10.43%로 많이 부족. 꾸준히 채워나가기 좋은 종목.

**AAPL (애플)** — 8주 · +34.66% · 어제 -1.75%
목표비중(8%) 대비 7.23%로 거의 근접. 버핏 최대 보유 종목과 겹쳐 안심하고 유지.

**NVDA (엔비디아)** — 2주 · +4.12% · 어제 -0.33%
목표비중(5%) 대비 1.63%로 많이 부족. AI 반도체 대장주, 분할로 꾸준히 채우기 권장.

**MSFT (마이크로소프트)** — 13주 · +24.34% · 어제 -0.47%
미장 포트폴리오 내 최대 비중(19.66%). 퍼싱스퀘어 2위 종목과 방향 일치. 유지.

**META (메타)** — 9주 · -9.38% · 어제 -0.04%
⚠️ 가장 신경 써야 할 종목. 목표비중 7% 대비 실제 21.18%로 3배 초과. 물타기보다 지수 조정 시 비중 축소(일부 매도) 고려.

**SPYM (S&P500 공격형)** — 24주 · +41.91% · 어제 -0.84%
목표비중(12%) 대비 5.93%로 부족. 꾸준히 채우는 종목.

**SCHD (배당 ETF)** — 42주 · +40.63% · 어제 -0.74%
탐욕 구간에서 상대적으로 안전한 배당 자산. 유지.

**SPYG (S&P500 방어형)** — 12주 · +26.57% · 어제 -0.70%
목표비중(10%) 대비 4.44%로 부족. 꾸준히 채우는 종목.

**ABBV (애브비)** — 5주 · +38.10% · 어제 -1.56%
배당수익률 2.76%의 방어적 헬스케어 배당주. 유지.

**O (리얼티인컴)** — 40주 · +16.07% · 어제 +0.35%
배당수익률 5.24%로 포트폴리오 내 최고 배당주. 목표비중(5%) 대비 8.51%로 초과 — 추가 매수는 잠시 멈추고 관망.

**MCD (맥도날드)** — 7주 · -1.90% · 어제 +0.63%
목표비중(5%) 대비 7.50%로 초과 상태지만 안정적 배당주라 손실 크지 않아 유지.
"""

MARKET_BRIEFING_13F = """
- **애플·구글·MS 겹침** — 버핏(애플 최대), 버핏(구글 대폭 확대), 퍼싱스퀘어(MS 2위)와 방향이 같은 안전한 축
- **META 21% 집중은 나만의 리스크** — 유명 투자자 중 META 보유는 퍼싱스퀘어뿐이고, 그마저 소수 종목 중 하나. "따라 하기"가 아니라 "나만 갖고 있는 리스크"
- **아마존(AMZN) 미보유** — 퍼싱스퀘어·애팔루사 둘 다 최상위 비중으로 보유 중인 종목. QQQM을 통한 간접 노출 외엔 없어 관심 가져볼 만한 공백
- **ETF 분산 전략은 브리지워터와 유사** — 브리지워터는 SPY·IVV 최대 비중 + 997개 종목 분산. QQQM·SPYM·SPYG·RISE 시리즈 등 ETF 비중이 상당해 분산 철학은 이미 잘 하고 있는 편
"""

st.subheader("오늘의 시장 브리핑")

anthropic_api_key = None
if "app" in st.secrets and st.secrets["app"].get("anthropic_api_key"):
    anthropic_api_key = st.secrets["app"]["anthropic_api_key"]

briefing_key = date.today().isoformat()

if not anthropic_api_key:
    st.info(
        "🔑 AI 자동 브리핑을 쓰려면 Anthropic API 키가 필요해요. "
        "console.anthropic.com에서 발급받아 Secrets의 `[app] anthropic_api_key`에 추가하면, "
        "여기서 '오늘의 브리핑 생성' 버튼이 나타나요. (호출마다 소액 과금됩니다.) "
        "지금은 예시로 만들어드렸던 샘플 브리핑을 보여드릴게요."
    )
    with st.expander("① 시장 리뷰 (국장 vs 미장) · 공포탐욕지수 (예시, 2026-08-20 기준)", expanded=False):
        st.markdown(MARKET_BRIEFING_INTRO)
    with st.expander("② 국내 주식 포트폴리오 코멘트 (예시)", expanded=False):
        st.markdown(MARKET_BRIEFING_KR)
    with st.expander("③ 미국 주식 포트폴리오 코멘트 (예시)", expanded=False):
        st.markdown(MARKET_BRIEFING_US)
    with st.expander("④ 13F(버핏 등 큰손 보유현황) 비교 (예시)", expanded=False):
        st.markdown(MARKET_BRIEFING_13F)
else:
    saved_briefing = None
    if history_sheet_id:
        try:
            saved_briefing = history_store.load_text_snapshot(_get_gc_client(), history_sheet_id, "ai_briefings", briefing_key)
        except Exception:
            saved_briefing = None

    col_gen, col_info = st.columns([1, 3])
    with col_gen:
        btn_label = "🔄 다시 생성" if saved_briefing else "✨ 오늘의 브리핑 생성"
        generate_clicked = st.button(btn_label, disabled=not all_sig_rows_for_ai)
    with col_info:
        if saved_briefing:
            st.caption(f"{briefing_key} 기준으로 이미 생성된 브리핑이에요. 저장돼있어서 새로고침해도 유지됩니다.")
        elif not all_sig_rows_for_ai:
            st.caption("보유 종목 데이터가 있어야 브리핑을 만들 수 있어요.")
        else:
            st.caption("웹 검색 + 종목 분석이라 생성에 10~30초 정도 걸려요.")

    if generate_clicked:
        try:
            with st.spinner("오늘의 시장을 조사하고 포트폴리오와 비교하는 중... (10~30초 소요)"):
                import ai_briefing
                new_briefing = ai_briefing.generate_market_briefing(anthropic_api_key, all_sig_rows_for_ai)
            saved_briefing = new_briefing
            if history_sheet_id:
                try:
                    history_store.save_text_snapshot(_get_gc_client(), history_sheet_id, "ai_briefings", briefing_key, new_briefing)
                except Exception:
                    st.warning("브리핑은 생성됐지만 저장에는 실패했어요. 새로고침하면 사라질 수 있어요.")
            st.rerun()
        except Exception as e:
            st.error(f"브리핑 생성에 실패했어요: {e}")

    if saved_briefing:
        st.markdown(saved_briefing)
    elif not generate_clicked:
        st.info("아직 오늘의 브리핑이 없어요. 위 버튼을 눌러 생성해보세요.")

st.caption("이 페이지는 열릴 때마다(최대 10분 캐시) 구글시트 최신 값을 다시 읽어옵니다.")
