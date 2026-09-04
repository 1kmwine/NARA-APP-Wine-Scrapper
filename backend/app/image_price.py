from __future__ import annotations
import logging
import time
from typing import Callable, Optional

from . import price_image_gemini, price_image_ocr

logger = logging.getLogger(__name__)

Extractor = Callable[[bytes, str], Optional[int]]

# 5MB 넘는 이미지는 건너뛴다 — 결제화면 캡처는 수백 KB면 충분하고, 큰 원본
# 사진을 그대로 모델에 실으면 호출이 느려지고 무료 티어 한도를 빨리 태운다.
MAX_IMAGE_BYTES = 5 * 1024 * 1024

# 글 하나에 이미지 분석으로 쓸 수 있는 시간(초). 가격검색 전체 제한이 300초인데
# 글이 25개씩 나오므로, 이미지가 붙은 글 몇 개가 분 단위로 잡아먹으면 전체가 끊긴다.
# ponytail: 글 단위 예산만 둔다 — 정교한 스케줄링은 실제로 모자랄 때 붙인다.
PER_POST_IMAGE_BUDGET_SECONDS = 25.0


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
    budget_seconds: float = PER_POST_IMAGE_BUDGET_SECONDS, now=time.monotonic,
) -> int | None:
    """이미지들을 순서대로 보다가 첫 성공 값에서 멈춘다. 결제화면이 여러 장인 글이
    흔한데 같은 값을 중복 저장할 이유가 없고, 호출도 아껴야 한다.

    글 하나에 쓸 수 있는 시간은 budget_seconds로 제한한다 — 이미지 한 장당
    다운로드 15초 + 추출기 20초라 상한이 없으면 글 하나가 분 단위로 잡아먹고
    전체 검색이 제한 시간에 걸린다(2026-09-04 실측: 한 글에서 40초 이상 정체).
    단 첫 장은 예산과 무관하게 항상 본다 — 안 그러면 이미지 경로가 통째로 죽는다."""
    started = now()
    for index, url in enumerate(image_urls):
        if index > 0 and (now() - started) >= budget_seconds:
            logger.info("이미지 분석 예산(%.0f초) 소진 — 남은 %d장 건너뜀",
                        budget_seconds, len(image_urls) - index)
            break
        downloaded = download_image(url, client, cookie=cookie)
        if downloaded is None:
            continue
        image_bytes, mime_type = downloaded
        price = extractor(image_bytes, mime_type)
        if price is not None:
            return price
    return None
