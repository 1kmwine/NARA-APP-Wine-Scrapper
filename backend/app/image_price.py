from __future__ import annotations
import logging
from typing import Callable, Optional

from . import price_image_gemini, price_image_ocr

logger = logging.getLogger(__name__)

Extractor = Callable[[bytes, str], Optional[int]]

# 5MB 넘는 이미지는 건너뛴다 — 결제화면 캡처는 수백 KB면 충분하고, 큰 원본
# 사진을 그대로 모델에 실으면 호출이 느려지고 무료 티어 한도를 빨리 태운다.
MAX_IMAGE_BYTES = 5 * 1024 * 1024


def download_image(url: str, client, cookie: str | None = None) -> tuple[bytes, str] | None:
    """이미지를 내려받아 (bytes, mime)을 돌려준다. 실패하거나 이미지가 아니면 None.

    Task 3에서 카페 CDN이 401/403을 내면 cookie를 넘겨 호출한다(네이버 로그인
    쿠키). 블로그 CDN(mblogthumb-phinf)은 쿠키 없이 받아진다 — 2026-09-03 확인."""
    headers = {"User-Agent": "Mozilla/5.0"}
    if cookie:
        headers["Cookie"] = cookie
    try:
        response = client.get(url, headers=headers, timeout=15.0)
        response.raise_for_status()
    except Exception:  # noqa: BLE001 — 이 이미지만 스킵
        logger.warning("이미지 다운로드 실패: %s", url)
        return None
    mime_type = (response.headers.get("content-type") or "").split(";")[0].strip()
    if not mime_type.startswith("image/"):
        return None
    if len(response.content) > MAX_IMAGE_BYTES:
        return None
    return response.content, mime_type


def get_extractor(name: str, api_key: str | None) -> Extractor | None:
    """환경변수 IMAGE_PRICE_EXTRACTOR 값으로 추출기를 고른다.

    기본값은 'off' — 벤치마크(scripts/bench_image_price.py)로 Gemini/OCR 중
    어느 쪽이 나은지 정하기 전까지는 이미지 경로를 켜지 않는다."""
    if name == "gemini":
        if not api_key:
            logger.warning("IMAGE_PRICE_EXTRACTOR=gemini인데 GEMINI_API_KEY가 없다 — 이미지 추출 비활성")
            return None
        return lambda image_bytes, mime_type: price_image_gemini.extract_final_price(
            image_bytes, mime_type, api_key=api_key)
    if name == "ocr":
        return price_image_ocr.extract_final_price
    return None


def extract_price_from_images(
    image_urls: list[str], client, extractor: Extractor, cookie: str | None = None,
) -> int | None:
    """이미지들을 순서대로 보다가 첫 성공 값에서 멈춘다. 결제화면이 여러 장인 글이
    흔한데 같은 값을 중복 저장할 이유가 없고, 호출도 아껴야 한다."""
    for url in image_urls:
        downloaded = download_image(url, client, cookie=cookie)
        if downloaded is None:
            continue
        image_bytes, mime_type = downloaded
        price = extractor(image_bytes, mime_type)
        if price is not None:
            return price
    return None
