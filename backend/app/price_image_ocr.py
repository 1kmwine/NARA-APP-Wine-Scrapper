from __future__ import annotations
import io
import logging
import re

logger = logging.getLogger(__name__)

# "최종 결제 금액", "결제금액", "총 결제 금액" 등 — 결제화면에서 최종 지불액을 가리키는 라벨.
_LABEL_RE = re.compile(r'(최종\s*결제\s*금액|총\s*결제\s*금액|결제\s*금액|최종\s*결제|결제금액)')
# OCR은 천 단위 구분자를 쉼표/마침표/공백 아무거나로 뱉는다 — 셋 다 허용하고,
# 구분자를 지운 뒤 4~6자리(1,000~999,999원)만 가격으로 인정한다.
# price_extraction._PRICE_RE는 "29,800원" 형태를 정확히 요구해서 OCR 잡음에 약하다.
_OCR_PRICE_RE = re.compile(r'(\d{1,3}(?:[,.\s]\d{3})+|\d{4,6})\s*원')


def _first_price(line: str) -> int | None:
    match = _OCR_PRICE_RE.search(line)
    if not match:
        return None
    digits = re.sub(r'[,.\s]', '', match.group(1))
    if not 4 <= len(digits) <= 6:
        return None
    return int(digits)


def parse_price_from_ocr_text(text: str) -> int | None:
    """OCR 텍스트에서 최종 결제금액을 찾는다. 결제 라벨과 같은 줄, 없으면 바로
    다음 줄에서 찾는다. 라벨이 없으면 None — '가장 큰 숫자'식 추측은 하지 않는다."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for index, line in enumerate(lines):
        if not _LABEL_RE.search(line):
            continue
        value = _first_price(line)
        if value is not None:
            return value
        if index + 1 < len(lines):
            value = _first_price(lines[index + 1])
            if value is not None:
                return value
    return None


def extract_final_price(image_bytes: bytes, mime_type: str) -> int | None:
    """Tesseract로 이미지를 읽어 최종 결제금액을 뽑는다. 언어팩 미설치 등
    OCR 실패는 예외 대신 None — 이 이미지만 스킵하고 검색은 계속된다.

    서버에 apt 패키지 tesseract-ocr, tesseract-ocr-kor 설치가 필요하다."""
    try:
        import pytesseract
        from PIL import Image

        text = pytesseract.image_to_string(Image.open(io.BytesIO(image_bytes)), lang="kor+eng")
    except Exception:  # noqa: BLE001 — 이 이미지만 스킵
        logger.exception("OCR 이미지 가격 추출 실패")
        return None
    return parse_price_from_ocr_text(text)
