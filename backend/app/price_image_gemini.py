from __future__ import annotations
import base64
import json
import logging

import httpx

from .brand_match import flexible_name_match, is_ascii_only

logger = logging.getLogger(__name__)

def build_prompt(query: str | None) -> str:
    """이미지에서 읽을 가격의 조건을 만든다.

    query(검색한 와인명)를 주면 "그 와인의 가격인지"를 모델이 먼저 판정하게
    한다 — 예전 프롬프트는 '이 이미지는 와인 구매/결제 화면'이라고 전제하고
    최종금액만 읽으라고 해서, 와인 글에 같이 올라온 다른 상품 사진의 가격을
    와인 가격으로 읽는 문제가 있었다(실측 2026-09-05 — "코스트코 프리미엄
    스시콤보 & 로저구라트 까바" 글의 초밥 영수증 49,990원이 로저구라트
    코스트코 가격으로 저장됨)."""
    target = (
        f"이 이미지에서 '{query}' 와인의 가격만 읽어라.\n"
        f"- 이미지에 보이는 상품이 '{query}' 와인이 아니면(예: 음식, 식품, 다른 주류, "
        "다른 상품의 영수증/가격표) 가격이 또렷하게 보여도 반드시 null로 답한다.\n"
        "- 와인병 사진에 붙은 가격표, 또는 영수증/결제화면에서 그 와인 품목 줄의 "
        "금액만 인정한다(영문·약칭 표기도 같은 와인이면 인정).\n"
        "- **가격표가 여러 개 찍힌 진열대 사진이 흔하다.** 각 가격표에 인쇄된 "
        f"상품명을 먼저 읽고, '{query}'와 같은 제품인 가격표 하나만 골라라. "
        "어느 가격표의 상품명도 그 와인이 아니면 null로 답한다. 병 사진 옆에 있다는 "
        "이유만으로 그 가격표를 고르지 마라.\n"
        "- 같은 영수증에 다른 품목이 섞여 있으면 그 와인 품목 줄의 금액만 읽고, "
        "합계/총액은 쓰지 않는다.\n"
        f"- matched_name에는 네가 실제로 고른 가격표/영수증 줄에 **인쇄된 상품명을 "
        "그대로** 적어라(네 해석이나 검색어를 그대로 베끼지 말 것). "
        "matches_target에는 그 상품명이 '" + str(query) + "'와 같은 제품인지 true/false로 답하라.\n"
        if query else
        "이 이미지는 와인 구매/결제 화면 캡처거나 행사 가격 안내다. "
        "소비자가 실제로 지불한 최종 결제금액(원)을 숫자 하나로만 읽어라.\n"
    )
    return (
        target
        + "- '최종 결제 금액', '결제 금액', '총 결제금액' 같은 라벨이 있으면 그 값을 쓴다.\n"
        "- 정가/총 상품금액과 할인 후 결제금액이 같이 있으면 할인 후 결제금액을 쓴다.\n"
        "- 가격이 안 보이거나 확신이 없으면 지어내지 말고 null로 답한다.\n"
        '반드시 이 JSON 형식으로만 답하라: '
        '{"final_price": 15920, "label": "최종 결제 금액", '
        '"matched_name": "가격표에 인쇄된 상품명", "matches_target": true} '
        '또는 {"final_price": null, "label": null, "matched_name": null, "matches_target": false}'
    )


# query 없이 호출하는 기존 코드(벤치마크 스크립트 등) 호환용
PROMPT = build_prompt(None)


def extract_final_price(
    image_bytes: bytes,
    mime_type: str,
    api_key: str,
    client=None,
    model: str = "gemini-flash-lite-latest",
    query: str | None = None,
) -> int | None:
    """이미지에서 최종 결제금액을 읽는다. 못 읽으면 None.

    query를 주면 그 와인의 가격만 인정한다 — 같은 글에 올라온 다른 상품
    (음식 등) 사진의 가격을 와인 가격으로 읽는 걸 막는다(build_prompt 참고).

    호출 실패(429/503/타임아웃)나 응답 파싱 실패는 예외를 던지지 않고 None —
    이 이미지 하나만 스킵하고 검색 전체는 계속돼야 한다.

    model 기본값이 -latest 별칭인 이유는 briefing_summary.call_gemini와 같다:
    이 API 키의 무료 티어는 버전 고정 모델이 quota=0이다.

    flash가 아니라 flash-lite인 이유: gemini-flash-latest는 무료 쿼터가 하루
    ~20건 수준이라 이미지 1장=1호출인 이 경로가 검색 몇 번에 429로 죽는다
    (실측 2026-09-05 — 종일 429). lite로 실측했을 때 가격표 판독·제품 판정이
    모두 정확했다: 켄달잭슨 가격표는 null, 같은 글의 로저구라트 가격표는
    19,990원, 케이머스 진열대(가격표 2개)에서는 위쪽 144,900원을 정확히 골랐다."""
    http = client or httpx
    try:
        response = http.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            params={"key": api_key},
            json={
                "contents": [{"parts": [
                    {"text": build_prompt(query)},
                    {"inlineData": {"mimeType": mime_type, "data": base64.b64encode(image_bytes).decode()}},
                ]}],
                "generationConfig": {"responseMimeType": "application/json", "temperature": 0.0},
            },
            # 30초였는데, 한 장이 오래 매달리면 글당 예산(image_price의 25초)을
            # 한 장이 다 먹는다 — 정상 응답은 실측 6초 안팎이라 20초면 충분하다.
            timeout=20.0,
        )
        response.raise_for_status()
        text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
        parsed = json.loads(text)
        value = parsed.get("final_price")
    except Exception:  # noqa: BLE001 — 이 이미지만 스킵
        logger.exception("Gemini 이미지 가격 추출 실패")
        return None
    if not isinstance(value, int):
        return None
    if query and not _name_verified(parsed, query):
        return None
    return value


def _name_verified(parsed: dict, query: str) -> bool:
    """모델이 고른 가격표의 상품명을 코드로 다시 검증한다 — 모델 판정만 믿으면
    진열대 사진에서 엉뚱한 가격표를 골라도 그대로 저장된다(실측 2026-09-05
    케이머스 사진의 "꼬르동루즈 샴페인 51,900원" 가격표).

    영문 가격표("CAYMUS")는 한글 검색어와 문자 비교가 불가능하므로 그 경우에만
    모델의 matches_target 판정을 신뢰한다."""
    matched_name = parsed.get("matched_name") or ""
    if not parsed.get("matches_target"):
        logger.info("이미지 가격 폐기 — 모델이 다른 제품으로 판정: %r", matched_name)
        return False
    if not matched_name:
        logger.info("이미지 가격 폐기 — 가격표 상품명 없음")
        return False
    if flexible_name_match(matched_name, query):
        return True
    if is_ascii_only(matched_name):
        return True  # 영문 표기 가격표 — 문자 비교 불가, 모델 판정 신뢰
    logger.info("이미지 가격 폐기 — 가격표 상품명(%r)이 검색어(%r)와 불일치",
                matched_name, query)
    return False
