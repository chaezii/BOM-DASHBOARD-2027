"""
fetch_data.py
서비스 계정으로 구글시트 3개(주식/자산현황/가계부)에 접속해서
대시보드에 필요한 숫자를 뽑아옵니다.

시트 URL의 '/d/'와 '/edit' 사이 부분이 스프레드시트 ID입니다.
예) https://docs.google.com/spreadsheets/d/<여기가 ID>/edit
"""

import gspread
from google.oauth2.service_account import Credentials

from sheet_utils import grid_find, to_number, find_table_total, find_date_in_row

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
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


def _all_values_first_sheet(gc: gspread.Client, sheet_id: str) -> list[list[str]]:
    sh = gc.open_by_key(sheet_id)
    ws = sh.get_worksheet(0)  # 첫 번째 탭만 사용 (자산현황, 주식 시트는 탭이 1개라 이걸로 충분)
    return ws.get_all_values()


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
    values = _all_values_first_sheet(gc, SHEET_IDS["asset"])

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
    }
    if debug:
        print("[asset_summary]", result)
    return result


# ---------------------------------------------------------------------------
# 2) 주식 포트폴리오 시트 (요약 표: 계좌명 / 매수금액 / 평가금액 / ... / 합계)
# ---------------------------------------------------------------------------
def fetch_stock_summary(gc: gspread.Client, debug: bool = False) -> dict:
    values = _all_values_first_sheet(gc, SHEET_IDS["stock"])

    totals = find_table_total(
        values,
        header_label="계좌명",
        columns=["매수금액", "평가금액", "수익", "현재 수익률 (5%이상 유지)", "보유수량"],
        total_label="합계",
    )
    result = {
        "total_buy": to_number(totals.get("매수금액")),
        "total_eval": to_number(totals.get("평가금액")),
        "total_profit": to_number(totals.get("수익")),
        "total_return_pct": to_number(totals.get("현재 수익률 (5%이상 유지)")),
        "total_shares": to_number(totals.get("보유수량")),
    }
    if debug:
        print("[stock_summary]", result)
    return result


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


def fetch_all(service_account_info: dict, debug: bool = False) -> dict:
    gc = get_client(service_account_info)
    return {
        "asset": fetch_asset_summary(gc, debug=debug),
        "stock": fetch_stock_summary(gc, debug=debug),
        "ledger": fetch_ledger_monthly(gc, debug=debug),
    }


if __name__ == "__main__":
    # 로컬 테스트용: service_account.json 파일을 이 스크립트와 같은 폴더에 두고 실행
    import json

    with open("service_account.json", encoding="utf-8") as f:
        sa_info = json.load(f)

    data = fetch_all(sa_info, debug=True)
    print(data)
