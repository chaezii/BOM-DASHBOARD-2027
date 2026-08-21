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
    """'₩1,196,547,592', '19.8%', '-114,500' 같은 문자열을 숫자로 변환.
    빈 칸/대시는 0으로, 수식 오류값(#N/A 등, 보통 실시간 시세 수식이 아직 못 불러온 경우)은
    None(값 없음)으로 구분해서 반환 - 오류를 진짜 0원처럼 잘못 보여주지 않기 위함."""
    if raw is None:
        return None
    s = str(raw).strip()
    if s in ("#DIV/0!", "#VALUE!", "#REF!", "#N/A", "#NAME?", "#NUM!", "#ERROR!"):
        return None  # 수식 오류 - 실시간 시세를 아직 못 불러왔을 가능성이 높음
    if s in ("", "-", "\u2212"):
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


def parse_asset_detail_items(
    values: list[list[str]],
    total_label: str = "자산",
) -> dict:
    """
    자산현황 시트 맨 위쪽, '항목명 | 금액' 형태로 나열된 개별 자산 라인들을
    {항목명: 금액} 딕셔너리로 반환. total_label(기본 '자산') 행을 만나면 멈춤.
    """
    total_matches = grid_find_all(values, total_label)
    if not total_matches:
        return {}
    total_row = total_matches[0][0]
    return _parse_label_value_rows(values, 0, total_row)


def parse_liability_detail_items(
    values: list[list[str]],
    start_label: str = "자산",
    end_label: str = "부채",
) -> dict:
    """
    '자산' 합계 행 다음부터 '부채' 합계 행 전까지 나열된 개별 부채(대출 등) 라인들을
    {항목명: 금액} 딕셔너리로 반환. 두 라벨 중 하나라도 없으면 빈 딕셔너리."""
    start_matches = grid_find_all(values, start_label)
    end_matches = grid_find_all(values, end_label)
    if not start_matches or not end_matches:
        return {}
    start_row = start_matches[0][0]
    end_row = None
    for r, _c in end_matches:
        if r > start_row:
            end_row = r
            break
    if end_row is None:
        return {}
    return _parse_label_value_rows(values, start_row + 1, end_row)


def _parse_label_value_rows(values: list[list[str]], from_row: int, to_row: int) -> dict:
    items = {}
    for r in range(from_row, to_row):
        row = values[r] if r < len(values) else None
        if not row:
            continue
        name = (row[0] or "").strip()
        if not name or name in ("항목", "합계"):
            continue
        value = None
        for c in range(1, min(len(row), 4)):
            v = to_number(row[c])
            if v:
                value = v
                break
        if value is not None:
            items[name] = value
    return items


def parse_monthly_category_table(
    values: list[list[str]],
    month_labels: tuple[str, ...] = tuple(f"{m}월" for m in range(1, 13)),
    total_label: str = "합계",
) -> dict:
    """
    '항목 | 합계 | 1월 | 2월 | ... | 12월' 형태의 표를 찾아서
    {"categories": {카테고리명: [1월값,...,12월값]}, "total": [1월합계,...,12월합계]} 로 반환.
    """
    header_row_idx = None
    month_col_positions: dict[str, int] = {}
    for r, row in enumerate(values):
        cells = [(c or "").strip() for c in row]
        if "1월" in cells and "12월" in cells:
            header_row_idx = r
            for c, cell in enumerate(cells):
                if cell in month_labels:
                    month_col_positions[cell] = c
            break

    if header_row_idx is None:
        return {}

    categories = {}
    total_row = None
    for r in range(header_row_idx + 1, len(values)):
        row = values[r]
        name = (row[0] or "").strip() if row else ""
        if not name:
            continue
        monthly = [to_number(row[month_col_positions[m]]) if month_col_positions.get(m, -1) < len(row) else None for m in month_labels]
        monthly = [v or 0 for v in monthly]
        if name == total_label:
            total_row = monthly
            break
        categories[name] = monthly

    return {"categories": categories, "total": total_row, "months": list(month_labels)}


def parse_ticker_tables(
    values: list[list[str]],
    required_headers: tuple[str, ...] = ("종목명", "종목코드"),
    section_labels: tuple[str, ...] = ("국내 주식 포트폴리오", "미국 주식 포트폴리오"),
) -> list[dict]:
    """
    시트 안에서 '종목명 / 종목코드' 등이 같이 있는 헤더 행을 전부 찾아서
    각 표를 [{market, columns:{...}}, ...] 형태로 파싱.
    market은 가장 가까운 위쪽의 section_labels 문구로 추정.
    """
    tables = []
    n_rows = len(values)
    for r, row in enumerate(values):
        cells = [(c or "").strip() for c in row]
        if all(h in cells for h in required_headers):
            col_positions = {}
            for c, cell in enumerate(cells):
                if cell:
                    col_positions[cell] = c

            # 가장 가까운 위쪽 섹션 라벨 찾기 (시장 구분용)
            market = "기타"
            for back in range(r - 1, max(r - 40, -1), -1):
                back_cells = [(c or "").strip() for c in values[back]]
                for label in section_labels:
                    if any(label in c for c in back_cells):
                        market = label.replace(" 주식 포트폴리오", "")
                        break
                if market != "기타":
                    break

            data_rows = []
            for dr in range(r + 1, n_rows):
                drow = values[dr]
                name_cell = drow[col_positions["종목명"]] if col_positions.get("종목명", -1) < len(drow) else ""
                if not name_cell or not str(name_cell).strip():
                    break
                if str(name_cell).strip().startswith("*"):
                    break
                data_rows.append(
                    {
                        col: (drow[pos] if pos < len(drow) else None)
                        for col, pos in col_positions.items()
                    }
                )
            tables.append({"market": market, "header_row": r, "rows": data_rows})
    return tables
