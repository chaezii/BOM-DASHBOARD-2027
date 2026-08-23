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


def _by_period_from_values(values: list[list[str]]) -> dict[str, list[dict]]:
    if not values or len(values) < 2:
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


def upsert_snapshot(
    gc: gspread.Client,
    history_sheet_id: str,
    tab_name: str,
    header: list[str],
    year_month: str,
    new_rows: list[list],
) -> dict[str, list[dict]]:
    """year_month(예: '2026-08')에 해당하는 기존 행들을 지우고 new_rows로 교체.
    다른 달의 기록은 그대로 남아있어서, 계속 쌓이며 기록이 됩니다.

    API 요청을 아끼려고, 저장 직후 다시 읽어오는 대신 방금 쓴 내용을 그대로
    {year_month: [row, ...]} 형태로 돌려줍니다 - 호출하는 쪽에서 추가로
    load_all_periods()를 또 부를 필요가 없어요."""
    sh = gc.open_by_key(history_sheet_id)
    try:
        ws = sh.worksheet(tab_name)
        existing = ws.get_all_values()
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=tab_name, rows=200, cols=max(len(header) + 2, 10))
        existing = []

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

    return _by_period_from_values(all_values)


def load_all_periods(
    gc: gspread.Client,
    history_sheet_id: str,
    tab_name: str,
) -> dict[str, list[dict]]:
    """저장된 모든 달의 데이터를 {year_month: [row_dict, ...]} 형태로 반환.
    (기록용 시트를 안 쓰거나, upsert 없이 조회만 하고 싶을 때 사용)"""
    try:
        sh = gc.open_by_key(history_sheet_id)
        ws = sh.worksheet(tab_name)
    except (gspread.SpreadsheetNotFound, gspread.WorksheetNotFound):
        return {}

    values = ws.get_all_values()
    return _by_period_from_values(values)


def upsert_value(
    gc: gspread.Client,
    history_sheet_id: str,
    tab_name: str,
    year_month: str,
    item: str,
    value: str,
) -> None:
    """(year_month, item) 조합 하나의 값을 갱신. 값은 문자열로 저장 (불리언 'TRUE'/'FALSE'든, 숫자든 그대로).
    다른 항목/다른 달 기록은 그대로 둠."""
    header = ["year_month", "item", "value"]
    sh = gc.open_by_key(history_sheet_id)
    try:
        ws = sh.worksheet(tab_name)
        existing = ws.get_all_values()
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=tab_name, rows=300, cols=6)
        existing = []

    data_rows = existing[1:] if len(existing) > 1 else []
    kept = [r for r in data_rows if not (len(r) >= 2 and r[0] == year_month and r[1] == item)]
    kept.append([year_month, item, value])

    all_values = [header] + kept
    needed_rows = len(all_values) + 20
    if ws.row_count < needed_rows:
        ws.resize(rows=needed_rows)
    ws.update(range_name="A1", values=all_values)


def load_values(gc: gspread.Client, history_sheet_id: str, tab_name: str) -> dict[str, dict[str, str]]:
    """{year_month: {item: value_문자열}} 형태로 전체 기록을 반환."""
    by_period = load_all_periods(gc, history_sheet_id, tab_name)
    result: dict[str, dict[str, str]] = {}
    for ym, rows in by_period.items():
        result[ym] = {row.get("item"): row.get("value", "") for row in rows}
    return result


def upsert_checklist_item(
    gc: gspread.Client,
    history_sheet_id: str,
    tab_name: str,
    year_month: str,
    item: str,
    checked: bool,
) -> None:
    """체크리스트 항목 하나(예: '2026-08'의 '지연 후불') 상태만 갱신.
    다른 항목/다른 달 기록은 그대로 둠."""
    header = ["year_month", "item", "checked"]
    sh = gc.open_by_key(history_sheet_id)
    try:
        ws = sh.worksheet(tab_name)
        existing = ws.get_all_values()
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=tab_name, rows=300, cols=6)
        existing = []

    data_rows = existing[1:] if len(existing) > 1 else []
    kept = [r for r in data_rows if not (len(r) >= 2 and r[0] == year_month and r[1] == item)]
    kept.append([year_month, item, "TRUE" if checked else "FALSE"])

    all_values = [header] + kept
    needed_rows = len(all_values) + 20
    if ws.row_count < needed_rows:
        ws.resize(rows=needed_rows)
    ws.update(range_name="A1", values=all_values)


def load_checklist(gc: gspread.Client, history_sheet_id: str, tab_name: str) -> dict[str, dict[str, bool]]:
    """{year_month: {item: True/False}} 형태로 전체 체크리스트 기록을 반환."""
    by_period = load_all_periods(gc, history_sheet_id, tab_name)
    result: dict[str, dict[str, bool]] = {}
    for ym, rows in by_period.items():
        result[ym] = {
            row.get("item"): str(row.get("checked", "")).strip().upper() == "TRUE" for row in rows
        }
    return result


def save_text_snapshot(
    gc: gspread.Client,
    history_sheet_id: str,
    tab_name: str,
    key: str,
    text: str,
) -> None:
    """key(예: 날짜 '2026-08-22')에 해당하는 긴 텍스트 하나를 저장. 같은 key면 덮어씀."""
    import datetime as _dt

    header = ["key", "text", "saved_at"]
    sh = gc.open_by_key(history_sheet_id)
    try:
        ws = sh.worksheet(tab_name)
        existing = ws.get_all_values()
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=tab_name, rows=50, cols=5)
        existing = []

    data_rows = existing[1:] if len(existing) > 1 else []
    kept = [r for r in data_rows if not (len(r) >= 1 and r[0] == key)]
    kept.append([key, text, _dt.datetime.utcnow().isoformat()])

    all_values = [header] + kept
    needed_rows = len(all_values) + 5
    if ws.row_count < needed_rows:
        ws.resize(rows=needed_rows)
    if ws.col_count < 3:
        ws.resize(cols=3)
    ws.update(range_name="A1", values=all_values)


def load_text_snapshot(
    gc: gspread.Client,
    history_sheet_id: str,
    tab_name: str,
    key: str,
) -> str | None:
    """key에 해당하는 저장된 텍스트를 반환. 없으면 None."""
    try:
        sh = gc.open_by_key(history_sheet_id)
        ws = sh.worksheet(tab_name)
    except (gspread.SpreadsheetNotFound, gspread.WorksheetNotFound):
        return None

    values = ws.get_all_values()
    for row in values[1:]:
        if row and row[0] == key:
            return row[1] if len(row) > 1 else None
    return None
    """start_ym부터 end_ym까지, 두 달 다 포함해서 몇 개월인지."""
    sy, sm = (int(x) for x in start_ym.split("-"))
    ey, em = (int(x) for x in end_ym.split("-"))
    return (ey - sy) * 12 + (em - sm) + 1


def previous_period(all_periods: dict, current_period: str) -> str | None:
    """current_period보다 이전인 것들 중 가장 최근 것을 반환 (YYYY-MM 문자열 비교라 정렬 가능)."""
    earlier = sorted(p for p in all_periods if p < current_period)
    return earlier[-1] if earlier else None


def months_between_inclusive(start_ym: str, end_ym: str) -> int:
    """start_ym부터 end_ym까지, 두 달 다 포함해서 몇 개월인지."""
    sy, sm = (int(x) for x in start_ym.split("-"))
    ey, em = (int(x) for x in end_ym.split("-"))
    return (ey - sy) * 12 + (em - sm) + 1


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
