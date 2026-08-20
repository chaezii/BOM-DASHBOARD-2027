"""
history_store.py
매달 스냅샷(자산 항목별 값, 종목별 값)을 별도의 "기록용" 구글시트에 저장하고,
저장된 이전 달 값을 불러와 전월 대비 비교를 할 수 있게 해줍니다.

왜 원래 3개 시트에 안 쓰고 새 시트를 쓰냐면:
- 원래 시트는 '뷰어(읽기 전용)' 권한만 공유했어서 안전합니다 (실수로 원본을 망가뜨릴 위험 없음)
- 기록용 시트는 서비스 계정에게 '편집자' 권한을 따로 줘야 하는데, 새 빈 시트라서 안전해요
"""

from __future__ import annotations

import gspread


def _get_or_create_worksheet(sh: gspread.Spreadsheet, title: str, header: list[str]) -> gspread.Worksheet:
    try:
        ws = sh.worksheet(title)
        existing_header = ws.row_values(1)
        if existing_header != header:
            ws.update(range_name="A1", values=[header])
        return ws
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=title, rows=200, cols=max(len(header) + 2, 10))
        ws.update(range_name="A1", values=[header])
        return ws


def upsert_snapshot(
    gc: gspread.Client,
    history_sheet_id: str,
    tab_name: str,
    header: list[str],
    year_month: str,
    new_rows: list[list],
) -> None:
    """year_month(예: '2026-08')에 해당하는 기존 행들을 지우고 new_rows로 교체.
    다른 달의 기록은 그대로 남아있어서, 계속 쌓이며 기록이 됩니다."""
    sh = gc.open_by_key(history_sheet_id)
    ws = _get_or_create_worksheet(sh, tab_name, header)

    existing = ws.get_all_values()
    data_rows = existing[1:] if len(existing) > 1 else []
    kept = [r for r in data_rows if r and r[0] != year_month]
    kept.extend([[year_month] + row for row in new_rows])

    all_values = [header] + kept
    needed_rows = len(all_values) + 20
    if ws.row_count < needed_rows:
        ws.resize(rows=needed_rows)
    ws.update(range_name="A1", values=all_values)
    # 남은 옛날 셀 찌꺼기 지우기 (혹시 이전 데이터가 더 길었을 경우 대비)
    if len(existing) > len(all_values):
        blank_rows = [[""] * len(header) for _ in range(len(existing) - len(all_values))]
        ws.update(range_name=f"A{len(all_values)+1}", values=blank_rows)


def load_all_periods(
    gc: gspread.Client,
    history_sheet_id: str,
    tab_name: str,
) -> dict[str, list[dict]]:
    """저장된 모든 달의 데이터를 {year_month: [row_dict, ...]} 형태로 반환."""
    try:
        sh = gc.open_by_key(history_sheet_id)
        ws = sh.worksheet(tab_name)
    except (gspread.SpreadsheetNotFound, gspread.WorksheetNotFound):
        return {}

    values = ws.get_all_values()
    if len(values) < 2:
        return {}

    header = values[0]
    by_period: dict[str, list[dict]] = {}
    for row in values[1:]:
        if not row or not row[0]:
            continue
        period = row[0]
        row_dict = {header[i]: (row[i] if i < len(row) else "") for i in range(len(header))}
        by_period.setdefault(period, []).append(row_dict)
    return by_period


def previous_period(all_periods: dict, current_period: str) -> str | None:
    """current_period보다 이전인 것들 중 가장 최근 것을 반환 (YYYY-MM 문자열 비교라 정렬 가능)."""
    earlier = sorted(p for p in all_periods if p < current_period)
    return earlier[-1] if earlier else None


def shift_year_month(year_month: str, months_back: int) -> str:
    """'2026-08'에서 months_back개월 전을 'YYYY-MM' 문자열로 계산."""
    y, m = (int(x) for x in year_month.split("-"))
    total = y * 12 + (m - 1) - months_back
    ny, nm = divmod(total, 12)
    return f"{ny:04d}-{nm + 1:02d}"


def period_at_or_before(all_periods, target_period: str) -> str | None:
    """target_period와 같거나 그 이전인 것들 중 가장 최근 기록을 반환."""
    candidates = sorted(p for p in all_periods if p <= target_period)
    return candidates[-1] if candidates else None
