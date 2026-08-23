"""
ai_insights.py
대시보드 자체 데이터(순자산/현금 목표, 소비, 투자 실행률, 주식 흐름 등)를 바탕으로
이번 달 인사이트와 보강해야 할 점을 Claude가 코멘트해줍니다.

시장 브리핑(ai_briefing.py, 현재 미사용)과 다르게 웹 검색을 안 써서 훨씬 저렴하고 빨라요.
한 달에 한 번 생성해서 기록용 시트에 저장해두는 방식으로 씁니다.
"""

from __future__ import annotations

import anthropic

MODEL = "claude-sonnet-5"

PROMPT_TEMPLATE = """아래는 한 사용자의 개인 자산관리 대시보드에서 뽑은 이번 달 데이터야.
이 데이터를 바탕으로 인사이트와 보강해야 할 점을 한국어로 코멘트해줘.

[이번 달 데이터]
{data_text}

다음 형식의 마크다운으로, 짧고 실용적으로 작성해줘 (이모지 적절히 활용):

## 이번 달 한눈에
(2~3문장 요약 - 가장 눈에 띄는 변화나 특징)

## 잘 하고 있는 것
(구체적인 숫자 근거와 함께 불릿 2~4개)

## 보강이 필요한 것
(구체적인 숫자 근거와 함께 불릿 2~4개 - 목표 대비 부족한 부분, 쏠림, 리스크 등)

## 다음 달 체크포인트
(실행 가능한 액션 1~3개)

너무 길지 않게, 실제로 읽을 만한 분량으로 작성해줘. 투자 조언이 아니라 참고 코멘트라는 점을
마지막에 한 문장으로 짧게 덧붙여줘.
"""


def generate_monthly_insight(api_key: str, data_text: str) -> str:
    """Claude API를 호출해서 이번 달 인사이트 markdown 텍스트를 반환.
    실패하면 예외를 그대로 던지므로, 호출하는 쪽에서 try/except로 감싸야 함."""
    client = anthropic.Anthropic(api_key=api_key)
    prompt = PROMPT_TEMPLATE.format(data_text=data_text)

    response = client.messages.create(
        model=MODEL,
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )

    text_parts = [block.text for block in response.content if getattr(block, "type", None) == "text"]
    return "\n\n".join(text_parts).strip()
