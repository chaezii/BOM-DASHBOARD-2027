"""
sheet_utils.py
구글시트에서 읽어온 2차원 리스트(values) 안에서 라벨(예: '순자산', '총 지출')을
텍스트로 찾아 옆 셀 값을 가져오는 헬퍼 모음.

셀 좌표를 하드코딩하지 않고 '라벨 검색' 방식을 쓰는 이유:
- 사용자가 행을 추가/삭제해도 어느 정도 안정적으로 동작합니다.
- 다만 같은 라벨이 시트 안에 여러 번 나오면 엉뚱한 값을 집을 수 있어요.
  그래서 occurrence(몇 번째로 매칭되는 것을 쓸지)를 지정할 수 있게 했습니다.
- 처음 실행할 때는 반드시 DEBUG=True로 한 번 돌려서 값이 맞는지 확인하세요.
"""

from __future__ import annotations
import re


def grid_find_all(values: list[list[str]], label: str) -> list[tuple[int, int]]:
    """values 안에서 정확히 label과 일치하는 셀의 (row, col) 좌표를 모두 반환."""
    matches = []
    for r, row in enumerate(values):
        for c, cell in enumerate(row):
            if cell is not None and str(cell).strip() == label:
                matches.append((r, c))
    return matches


def grid_find(
    values: list[list[str]],
    label: str,
    occurrence: int = 0,
    row_offset: int = 0,
    col_offset: int = 1,
):
    """label의 occurrence번째 매칭 위치에서 (row_offset, col_offset)만큼 떨어진 셀 값을 반환."""
    matches = grid_find_all(values, label)
    if len(matches) <= occurrence:
        return None
    r, c = matches[occurrence]
    rr, cc = r + row_offset, c + col_offset
    if 0 <= rr < len(values) and 0 <= cc < len(values[rr]):
        return values[rr][cc]
    return None


def to_number(raw) -> float | None:
    """'₩1,196,547,592', '19.8%', '-114,500' 같은 문자열을 숫자로 변환."""
    if raw is None:
        return None
    s = str(raw).strip()
    if s in ("", "-", "\u2212", "#DIV/0!", "#VALUE!", "#REF!", "#N/A"):
        return 0.0
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    s = s.replace(",", "").replace("원", "").replace("₩", "").replace("%", "").strip()
    s = s.replace("\u25b2", "").replace("\u25bc", "")
    try:
        val = float(s)
        return -val if neg else val
    except ValueError:
        return None


def find_date_in_row(row: list[str]) -> str | None:
    """행 안에서 '2026. 1. 1' 같은 날짜 패턴을 찾아 반환."""
    pattern = re.compile(r"\d{4}\D+\d{1,2}\D+\d{1,2}")
    for cell in row:
        if cell and pattern.search(str(cell)):
            return pattern.search(str(cell)).group()
    return None


def find_table_total(
    values: list[list[str]],
    header_label: str,
    columns: list[str],
    total_label: str = "합계",
    search_window: int = 15,
) -> dict:
    """
    header_label(예: '계좌명')이 있는 헤더 행을 찾고,
    그 아래 search_window행 안에서 첫 total_label(예: '합계') 행을 찾아
    columns 리스트 순서대로 값을 매핑해서 돌려줌.
    """
    header_matches = grid_find_all(values, header_label)
    if not header_matches:
        return {}
    hr, hc = header_matches[0]
    header_row = values[hr]

    # 헤더 행에서 각 컬럼명의 실제 위치(offset) 찾기
    col_positions = {}
    for i in range(hc, min(hc + 20, len(header_row))):
        cell = header_row[i].strip() if header_row[i] else ""
        if cell in columns:
            col_positions[cell] = i

    for r in range(hr + 1, min(hr + 1 + search_window, len(values))):
        row = values[r]
        if row and row[0:3] and any(
            (cell or "").strip() == total_label for cell in row[: hc + 1]
        ):
            return {
                col: (row[pos] if pos < len(row) else None)
                for col, pos in col_positions.items()
            }
    return {}
