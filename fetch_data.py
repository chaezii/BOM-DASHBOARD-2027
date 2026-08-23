"""
fetch_data.py
서비스 계정으로 구글시트 3개(주식/자산현황/가계부)에 접속해서
대시보드에 필요한 숫자를 뽑아옵니다.

시트 URL의 '/d/'와 '/edit' 사이 부분이 스프레드시트 ID입니다.
예) https://docs.google.com/spreadsheets/d/<여기가 ID>/edit
"""

import gspread
from google.oauth2.service_account import Credentials

from sheet_utils import (
    grid_find,
    to_number,
    find_table_total,
    find_date_in_row,
    parse_asset_detail_items,
    parse_liability_detail_items,
    parse_ticker_tables,
    parse_monthly_category_table,
)
import history_store

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",  # 기록용 시트에 '쓰기'까지 하려면 readonly가 아니어야 함
    "https://www.googleapis.com/auth/drive.readonly",
]

SHEET_IDS = {
    "stock": "1cTsLKnO_Ag4nrVtunRBo52Bu1wPlXHcEBf0HeDucIac",
    "asset": "19laTbY36AN6G6A64wLMMl1m0eIzGbzAHafBfebx81Yw",
    "ledger": "123NquXeQmjnQFy1A-55QilH8XRJf_W45wOAaq_S-81w",
}


def get_client(service_account_info: dict) -> gspread.Client:
    creds = Credentials.from_service_account_info(service_account_info, scopes=SCOPES)
    return gspread.authorize(creds)


def _find_worksheet_containing(worksheets: list[tuple[str, list]], label: str):
    """label이라는 글자가 들어있는 첫 번째 탭을 찾아서 (탭이름, 값들)을 반환.
    못 찾으면 (None, None)."""
    for name, values in worksheets:
        for row in values:
            for cell in row:
                if cell and str(cell).strip() == label:
                    return name, values
    return None, None


def _all_worksheets_values(gc: gspread.Client, sheet_id: str) -> list[tuple[str, list[list[str]]]]:
    """스프레드시트 안의 '모든' 탭을 각각 (탭이름, 값들) 형태로 반환.
    가계부처럼 탭이 월별로 나뉘어 있는 문서에 사용.

    ⚠️ 탭마다 따로따로 요청을 보내면 구글 API 할당량(분당 읽기 횟수)을 금방 넘겨서
    'Quota exceeded' 에러가 납니다. 그래서 여러 탭을 '한 번의 요청'으로 묶어서 가져옵니다
    (batchGet). 혹시 이 방식이 실패하면(구버전 라이브러리 등) 예전 방식(탭별로 하나씩)으로
    자동 전환합니다."""
    sh = gc.open_by_key(sheet_id)
    worksheets = sh.worksheets()
    if not worksheets:
        return []

    try:
        ranges = [f"'{ws.title}'" for ws in worksheets]
        batch = sh.values_batch_get(ranges)
        value_ranges = batch.get("valueRanges", [])
        result = []
        for ws, vr in zip(worksheets, value_ranges):
            result.append((ws.title, vr.get("values", [])))
        return result
    except Exception:
        # 배치 요청이 안 되면(옛날 라이브러리 등) 예전처럼 탭별로 하나씩 요청
        result = []
        for ws in worksheets:
            try:
                result.append((ws.title, ws.get_all_values()))
            except Exception:
                continue
        return result


# ---------------------------------------------------------------------------
# 1) 자산현황 시트
# ---------------------------------------------------------------------------
def fetch_asset_summary(gc: gspread.Client, worksheets=None, debug: bool = False) -> dict:
    if worksheets is None:
        worksheets = _all_worksheets_values(gc, SHEET_IDS["asset"])
    if debug:
        print(f"[asset] 총 {len(worksheets)}개 탭:", [n for n, _ in worksheets])

    tab_name, values = _find_worksheet_containing(worksheets, "순자산")
    if values is None:
        if debug:
            print("[asset] '순자산' 이라는 글자를 어느 탭에서도 못 찾았습니다.")
        return {}
    if debug:
        print(f"[asset] '{tab_name}' 탭에서 데이터를 찾았습니다.")

    def val(label, occurrence=0):
        return to_number(grid_find(values, label, occurrence=occurrence))

    result = {
        "total_assets": val("자산"),
        "total_debt": val("부채"),
        "net_worth": val("순자산"),
        "cash": val("현금"),
        "stocks": val("주식"),
        "pension": val("퇴직연금"),
        "crypto": val("가상화폐"),
        "real_estate": val("부동산"),
        "etc": val("기타"),
        "items": parse_asset_detail_items(values),  # 개별 항목별 금액 (은행 예금, 계좌, 부동산 등)
        "liability_items": parse_liability_detail_items(values),  # 개별 부채(대출 등) 항목
    }
    if debug:
        print("[asset_summary]", {k: v for k, v in result.items() if k != "items"})
        print("[asset_items]", result["items"])
    return result


# ---------------------------------------------------------------------------
# 1-1) 자산현황 파일의 '소비관리' 탭 (카테고리별 월간 지출)
# ---------------------------------------------------------------------------
def fetch_asset_spending_categories(gc: gspread.Client, worksheets=None, debug: bool = False) -> dict:
    if worksheets is None:
        worksheets = _all_worksheets_values(gc, SHEET_IDS["asset"])

    tab_name, values = _find_worksheet_containing(worksheets, "Eat")
    if values is None:
        # 'Eat' 라벨이 없으면, 월 헤더(1월~12월)만으로도 찾아봄
        for tname, tvalues in worksheets:
            parsed = parse_monthly_category_table(tvalues)
            if parsed.get("categories"):
                tab_name, values = tname, tvalues
                break

    if values is None:
        if debug:
            print("[spending] '소비관리' 탭을 찾지 못했습니다.")
        return {}

    parsed = parse_monthly_category_table(values)
    if debug:
        print(f"[spending] '{tab_name}' 탭에서 파싱:", parsed)
    return parsed


# ---------------------------------------------------------------------------
# 2) 주식 포트폴리오 시트 (요약 표: 계좌명 / 매수금액 / 평가금액 / ... / 합계)
# ---------------------------------------------------------------------------
def fetch_stock_summary(gc: gspread.Client, debug: bool = False) -> dict:
    worksheets = _all_worksheets_values(gc, SHEET_IDS["stock"])
    if debug:
        print(f"[stock] 총 {len(worksheets)}개 탭:", [n for n, _ in worksheets])

    tab_name, values = _find_worksheet_containing(worksheets, "계좌명")
    if values is None:
        if debug:
            print("[stock] '계좌명' 이라는 글자를 어느 탭에서도 못 찾았습니다.")
        totals = {}
    else:
        if debug:
            print(f"[stock] '{tab_name}' 탭에서 계좌 요약을 찾았습니다.")
        totals = find_table_total(
            values,
            header_label="계좌명",
            columns=["매수금액", "평가금액", "수익", "현재 수익률 (5%이상 유지)", "보유수량"],
            total_label="합계",
        )

    # 종목(티커)은 계좌 요약과 다른 탭에 있을 수 있어서, 모든 탭을 다 뒤져서 찾습니다.
    tickers = []
    for tname, tvalues in worksheets:
        found = _parse_all_tickers(tvalues)
        if found and debug:
            print(f"[stock] '{tname}' 탭에서 종목 {len(found)}개 발견")
        tickers.extend(found)

    result = {
        "total_buy": to_number(totals.get("매수금액")),
        "total_eval": to_number(totals.get("평가금액")),
        "total_profit": to_number(totals.get("수익")),
        "total_return_pct": to_number(totals.get("현재 수익률 (5%이상 유지)")),
        "total_shares": to_number(totals.get("보유수량")),
        "tickers": tickers,
    }
    if debug:
        print("[stock_summary]", {k: v for k, v in result.items() if k != "tickers"})
        print(f"[stock_tickers] 총 {len(result['tickers'])}개 종목 발견")
        for t in result["tickers"]:
            print("  ", t)
        if not result["tickers"]:
            print("  -> 어느 탭에서도 '종목명'+'종목코드' 헤더를 못 찾았습니다. "
                  "실제 시트의 헤더 문구가 다른지 확인이 필요합니다.")
    return result


def _parse_all_tickers(values: list[list[str]]) -> list[dict]:
    """국내/미국/연금 등 모든 티커 표를 하나의 리스트로 합쳐서 정리."""
    tables = parse_ticker_tables(values)
    tickers = []
    for table in tables:
        for row in table["rows"]:
            tickers.append(
                {
                    "market": table["market"],
                    "account": (row.get("계좌") or "").strip(),
                    "name": (row.get("종목명") or "").strip(),
                    "code": (row.get("종목코드") or "").strip(),
                    "eval_amount": to_number(row.get("총평가금액") or row.get("평가금액")),
                    "buy_amount": to_number(row.get("총매수금액") or row.get("매수금액")),
                    "quantity": to_number(row.get("보유수량")),
                    "profit": to_number(row.get("손익")),
                    "return_pct": to_number(row.get("수익률(%)")),
                    "price": to_number(row.get("현재가")),
                    "avg_buy_price": to_number(row.get("평단가")),
                    "target_weight_pct": to_number(row.get("목표 비중")),
                    "current_weight_pct": to_number(row.get("현재 비중")),
                }
            )
    return tickers


# ---------------------------------------------------------------------------
# 3) 가계부 시트 (연도별로 월 블록이 반복되는 구조: '시작일' 라벨마다 총수입/총지출/총저축)
# ---------------------------------------------------------------------------
def fetch_ledger_monthly(gc: gspread.Client, year: int = 2026, debug: bool = False) -> list[dict]:
    # 가계부는 탭이 월별로 나뉘어 있을 수 있어서, 모든 탭을 다 훑습니다.
    worksheets = _all_worksheets_values(gc, SHEET_IDS["ledger"])
    if debug:
        print(f"[ledger] 총 {len(worksheets)}개 탭 발견:", [name for name, _ in worksheets])

    months = []
    seen_dates = set()

    for tab_name, values in worksheets:
        start_markers = []
        for r, row in enumerate(values):
            if any((cell or "").strip() == "시작일" for cell in row):
                start_markers.append(r)

        for r in start_markers:
            date_str = find_date_in_row(values[r])
            if not date_str or str(year) not in date_str:
                continue
            if date_str in seen_dates:  # 같은 월이 여러 탭에 중복되지 않게
                continue

            window = values[r : r + 10]

            def find_in_window(label):
                for wrow in window:
                    for wc, cell in enumerate(wrow):
                        if cell and str(cell).strip() == label:
                            if wc + 1 < len(wrow):
                                return wrow[wc + 1]
                return None

            income = to_number(find_in_window("총 수입"))
            expense = to_number(find_in_window("총 지출"))
            saving = to_number(find_in_window("총 저축"))
            fixed_expense = _find_fixed_expense_in_tab(values)

            seen_dates.add(date_str)
            months.append(
                {
                    "date": date_str,
                    "tab": tab_name,
                    "income": income,
                    "expense": expense,
                    "saving": saving,
                    "fixed_expense": fixed_expense,
                }
            )

    months.sort(key=lambda m: m["date"])

    if debug:
        print("[ledger_monthly]")
        for m in months:
            print("  ", m)
        if not months:
            print("  -> 아무 달도 못 찾았습니다. 탭 이름/'시작일' 라벨이 실제 시트와 맞는지 확인하세요.")
    return months


def _find_fixed_expense_in_tab(values: list[list[str]]):
    """이 탭(월) 안에서 '고정지출' 라벨을 찾아 그 옆(같은 행, 오른쪽) 첫 숫자 값을 반환.
    라벨을 못 찾으면 F80 셀(사용자가 알려준 위치, 0-index로 행79/열5)을 마지막 수단으로 사용."""
    for row in values:
        for c, cell in enumerate(row):
            if cell and "고정지출" in str(cell):
                for cc in range(c + 1, len(row)):
                    v = to_number(row[cc])
                    if v:
                        return v
    # 라벨을 못 찾았을 때의 폴백: F80 (엑셀 표기 F80 = 0-index 행79, 열5)
    if len(values) > 79 and len(values[79]) > 5:
        v = to_number(values[79][5])
        if v:
            return v
    return None


def fetch_stock_monthly_trend(gc: gspread.Client, history_sheet_id: str) -> list[dict]:
    """기록용 시트의 stock_snapshots(모든 티커, 모든 달)를 월별로 집계해서
    [{"year_month":..,"avg_return_pct":..,"total_profit":..}, ...] 로 반환 (오래된 달 -> 최신 달 순)."""
    by_period = history_store.load_all_periods(gc, history_sheet_id, "stock_snapshots")
    result = []
    for ym in sorted(by_period.keys()):
        rows = by_period[ym]
        returns = [to_number(r.get("return_pct")) for r in rows]
        returns = [r for r in returns if r is not None]
        profits = [to_number(r.get("profit")) for r in rows]
        profits = [p for p in profits if p is not None]
        result.append({
            "year_month": ym,
            "avg_return_pct": (sum(returns) / len(returns)) if returns else None,
            "total_profit": sum(profits) if profits else None,
        })
    return result


def fetch_all(
    service_account_info: dict,
    history_sheet_id: str | None = None,
    year_month: str | None = None,
    debug: bool = False,
) -> dict:
    import datetime

    gc = get_client(service_account_info)
    year_month = year_month or datetime.date.today().strftime("%Y-%m")

    asset_worksheets = _all_worksheets_values(gc, SHEET_IDS["asset"])  # 자산 시트는 한 번만 읽어서 재사용
    asset = fetch_asset_summary(gc, worksheets=asset_worksheets, debug=debug)
    stock = fetch_stock_summary(gc, debug=debug)
    ledger = fetch_ledger_monthly(gc, debug=debug)
    spending = fetch_asset_spending_categories(gc, worksheets=asset_worksheets, debug=debug)

    asset_prev_items: dict = {}
    ticker_prev: dict = {}
    stock_trend: dict = {}

    if history_sheet_id:
        # --- 자산 항목 스냅샷 저장 + 지난달 값 불러오기 (저장한 결과를 그대로 재사용, 추가 조회 없음) ---
        asset_header = ["year_month", "item", "value"]
        asset_new_rows = [[name, str(value)] for name, value in (asset.get("items") or {}).items()]
        all_asset_periods = history_store.upsert_snapshot(
            gc, history_sheet_id, "asset_snapshots", asset_header, year_month, asset_new_rows
        )
        prev_ym = history_store.previous_period(all_asset_periods, year_month)
        if prev_ym:
            asset_prev_items = {
                row["item"]: to_number(row["value"]) for row in all_asset_periods[prev_ym]
            }
        if debug:
            print(f"[history] asset 이전 기록 달: {prev_ym}, 항목 수: {len(asset_prev_items)}")

        # --- 티커 스냅샷 저장 + 지난달 값 불러오기 ---
        ticker_header = [
            "year_month", "market", "account", "code", "name",
            "eval_amount", "buy_amount", "quantity", "profit", "return_pct", "price",
        ]
        ticker_new_rows = [
            [
                t["market"], t["account"], t["code"], t["name"],
                str(t.get("eval_amount") or ""), str(t.get("buy_amount") or ""),
                str(t.get("quantity") or ""), str(t.get("profit") or ""),
                str(t.get("return_pct") or ""), str(t.get("price") or ""),
            ]
            for t in (stock.get("tickers") or [])
        ]
        all_ticker_periods = history_store.upsert_snapshot(
            gc, history_sheet_id, "stock_snapshots", ticker_header, year_month, ticker_new_rows
        )
        prev_ym2 = history_store.previous_period(all_ticker_periods, year_month)
        if prev_ym2:
            for row in all_ticker_periods[prev_ym2]:
                key = f"{row['market']}|{row['account']}|{row['code']}"
                ticker_prev[key] = row
        if debug:
            print(f"[history] stock 이전 기록 달: {prev_ym2}, 종목 수: {len(ticker_prev)}")

        # --- 포트폴리오 총액 스냅샷 저장 + 3개월전/6개월전 값 불러오기 ---
        totals_header = ["year_month", "total_buy", "total_eval", "total_profit", "total_return_pct"]
        all_totals_periods = history_store.upsert_snapshot(
            gc, history_sheet_id, "portfolio_totals", totals_header, year_month,
            [[
                str(stock.get("total_buy") or ""),
                str(stock.get("total_eval") or ""),
                str(stock.get("total_profit") or ""),
                str(stock.get("total_return_pct") or ""),
            ]],
        )

        def _totals_at(period_row):
            if not period_row:
                return None
            row = period_row[0]
            return {
                "total_buy": to_number(row.get("total_buy")),
                "total_eval": to_number(row.get("total_eval")),
                "total_profit": to_number(row.get("total_profit")),
                "total_return_pct": to_number(row.get("total_return_pct")),
            }

        target_3m = history_store.shift_year_month(year_month, 3)
        target_6m = history_store.shift_year_month(year_month, 6)
        period_3m = history_store.period_at_or_before(all_totals_periods, target_3m)
        period_6m = history_store.period_at_or_before(all_totals_periods, target_6m)

        stock_trend = {
            "current": {
                "period": year_month,
                "total_buy": stock.get("total_buy"),
                "total_eval": stock.get("total_eval"),
                "total_profit": stock.get("total_profit"),
                "total_return_pct": stock.get("total_return_pct"),
            },
            "3m_ago": {"period": period_3m, **(_totals_at(all_totals_periods.get(period_3m)) or {})} if period_3m else None,
            "6m_ago": {"period": period_6m, **(_totals_at(all_totals_periods.get(period_6m)) or {})} if period_6m else None,
        }
        if debug:
            print("[history] stock_trend:", stock_trend)

        # --- 순자산/현금 월별 스냅샷 저장 (게이지를 월별 그래프로 보여주기 위함) ---
        liability_items_sum = sum((asset.get("liability_items") or {}).values())
        liability_total = liability_items_sum if liability_items_sum else (asset.get("total_debt") or 0)
        asset_total = sum((asset.get("items") or {}).values())
        net_worth_now = asset_total - liability_total
        networth_header = ["year_month", "cash", "net_worth", "total_assets", "total_debt"]
        all_networth_periods = history_store.upsert_snapshot(
            gc, history_sheet_id, "networth_history", networth_header, year_month,
            [[
                str(asset.get("cash") or ""),
                str(net_worth_now or ""),
                str(asset_total or ""),
                str(liability_total or ""),
            ]],
        )
        networth_history = []
        for ym in sorted(all_networth_periods.keys()):
            row = all_networth_periods[ym][0]
            networth_history.append({
                "year_month": ym,
                "cash": to_number(row.get("cash")),
                "net_worth": to_number(row.get("net_worth")),
                "total_assets": to_number(row.get("total_assets")),
                "total_debt": to_number(row.get("total_debt")),
            })
        if debug:
            print(f"[history] networth_history: {len(networth_history)}개월 기록")
        stock_monthly_trend = fetch_stock_monthly_trend(gc, history_sheet_id)
    else:
        networth_history = []
        stock_monthly_trend = []

    return {
        "year_month": year_month,
        "asset": asset,
        "stock": stock,
        "ledger": ledger,
        "spending": spending,
        "asset_prev_items": asset_prev_items,
        "ticker_prev": ticker_prev,
        "stock_trend": stock_trend,
        "networth_history": networth_history,
        "stock_monthly_trend": stock_monthly_trend,
    }


if __name__ == "__main__":
    # 로컬 테스트용: service_account.json 파일을 이 스크립트와 같은 폴더에 두고 실행
    import json

    with open("service_account.json", encoding="utf-8") as f:
        sa_info = json.load(f)

    data = fetch_all(sa_info, history_sheet_id=None, debug=True)
    print(data)
