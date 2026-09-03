from __future__ import annotations
import base64
import json
import logging

import httpx

logger = logging.getLogger(__name__)

PROMPT = (
    "이 이미지는 와인 구매/결제 화면 캡처거나 행사 가격 안내다. "
    "소비자가 실제로 지불한 최종 결제금액(원)을 숫자 하나로만 읽어라.\n"
    "- '최종 결제 금액', '결제 금액', '총 결제금액' 같은 라벨이 있으면 그 값을 쓴다.\n"
    "- 정가/총 상품금액과 할인 후 결제금액이 같이 있으면 할인 후 결제금액을 쓴다.\n"
    "- 가격이 안 보이거나 확신이 없으면 지어내지 말고 null로 답한다.\n"
    '반드시 이 JSON 형식으로만 답하라: {"final_price": 15920, "label": "최종 결제 금액"} '
    '또는 {"final_price": null, "label": null}'
)


def extract_final_price(
    image_bytes: bytes,
    mime_type: str,
    api_key: str,
    client=None,
    model: str = "gemini-flash-latest",
) -> int | None:
    """이미지에서 최종 결제금액을 읽는다. 못 읽으면 None.

    호출 실패(429/503/타임아웃)나 응답 파싱 실패는 예외를 던지지 않고 None —
    이 이미지 하나만 스킵하고 검색 전체는 계속돼야 한다.

    model 기본값이 -latest 별칭인 이유는 briefing_summary.call_gemini와 같다:
    이 API 키의 무료 티어는 버전 고정 모델이 quota=0이다."""
    http = client or httpx
    try:
        response = http.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            params={"key": api_key},
            json={
                "contents": [{"parts": [
                    {"text": PROMPT},
                    {"inlineData": {"mimeType": mime_type, "data": base64.b64encode(image_bytes).decode()}},
                ]}],
                "generationConfig": {"responseMimeType": "application/json", "temperature": 0.0},
            },
            timeout=30.0,
        )
        response.raise_for_status()
        text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
        value = json.loads(text).get("final_price")
    except Exception:  # noqa: BLE001 — 이 이미지만 스킵
        logger.exception("Gemini 이미지 가격 추출 실패")
        return None
    return value if isinstance(value, int) else None
