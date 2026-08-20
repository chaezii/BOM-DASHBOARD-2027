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
    parse_ticker_tables,
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
    가계부처럼 탭이 월별로 나뉘어 있는 문서에 사용."""
    sh = gc.open_by_key(sheet_id)
    result = []
    for ws in sh.worksheets():
        try:
            result.append((ws.title, ws.get_all_values()))
        except Exception:
            continue
    return result


# ---------------------------------------------------------------------------
# 1) 자산현황 시트
# ---------------------------------------------------------------------------
def fetch_asset_summary(gc: gspread.Client, debug: bool = False) -> dict:
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
    }
    if debug:
        print("[asset_summary]", {k: v for k, v in result.items() if k != "items"})
        print("[asset_items]", result["items"])
    return result


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

            seen_dates.add(date_str)
            months.append(
                {
                    "date": date_str,
                    "tab": tab_name,
                    "income": income,
                    "expense": expense,
                    "saving": saving,
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


def fetch_all(
    service_account_info: dict,
    history_sheet_id: str | None = None,
    year_month: str | None = None,
    debug: bool = False,
) -> dict:
    import datetime

    gc = get_client(service_account_info)
    year_month = year_month or datetime.date.today().strftime("%Y-%m")

    asset = fetch_asset_summary(gc, debug=debug)
    stock = fetch_stock_summary(gc, debug=debug)
    ledger = fetch_ledger_monthly(gc, debug=debug)

    asset_prev_items: dict = {}
    ticker_prev: dict = {}

    if history_sheet_id:
        # --- 자산 항목 스냅샷 저장 + 지난달 값 불러오기 ---
        asset_header = ["year_month", "item", "value"]
        if asset.get("items"):
            new_rows = [[name, str(value)] for name, value in asset["items"].items()]
            history_store.upsert_snapshot(
                gc, history_sheet_id, "asset_snapshots", asset_header, year_month, new_rows
            )
        all_asset_periods = history_store.load_all_periods(gc, history_sheet_id, "asset_snapshots")
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
        if stock.get("tickers"):
            new_rows = [
                [
                    t["market"], t["account"], t["code"], t["name"],
                    str(t.get("eval_amount") or ""), str(t.get("buy_amount") or ""),
                    str(t.get("quantity") or ""), str(t.get("profit") or ""),
                    str(t.get("return_pct") or ""), str(t.get("price") or ""),
                ]
                for t in stock["tickers"]
            ]
            history_store.upsert_snapshot(
                gc, history_sheet_id, "stock_snapshots", ticker_header, year_month, new_rows
            )
        all_ticker_periods = history_store.load_all_periods(gc, history_sheet_id, "stock_snapshots")
        prev_ym2 = history_store.previous_period(all_ticker_periods, year_month)
        if prev_ym2:
            for row in all_ticker_periods[prev_ym2]:
                key = f"{row['market']}|{row['account']}|{row['code']}"
                ticker_prev[key] = row
        if debug:
            print(f"[history] stock 이전 기록 달: {prev_ym2}, 종목 수: {len(ticker_prev)}")

    return {
        "year_month": year_month,
        "asset": asset,
        "stock": stock,
        "ledger": ledger,
        "asset_prev_items": asset_prev_items,
        "ticker_prev": ticker_prev,
    }


if __name__ == "__main__":
    # 로컬 테스트용: service_account.json 파일을 이 스크립트와 같은 폴더에 두고 실행
    import json

    with open("service_account.json", encoding="utf-8") as f:
        sa_info = json.load(f)

    data = fetch_all(sa_info, history_sheet_id=None, debug=True)
    print(data)
