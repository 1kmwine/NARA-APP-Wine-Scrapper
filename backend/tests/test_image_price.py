from app.image_price import download_image, extract_price_from_images, get_extractor


class FakeImageResponse:
    def __init__(self, content=b"bytes", content_type="image/png", status_code=200):
        self.content = content
        self.headers = {"content-type": content_type}
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeImageClient:
    def __init__(self, response_by_url):
        self._responses = response_by_url
        self.calls = []

    def get(self, url, *, headers=None, timeout=None):
        self.calls.append({"url": url, "headers": headers})
        response = self._responses.get(url)
        if response is None:
            raise RuntimeError("not found")
        return response


def test_download_image_returns_bytes_and_mime():
    client = FakeImageClient({"https://x/a.png": FakeImageResponse(b"png-bytes", "image/png")})

    assert download_image("https://x/a.png", client) == (b"png-bytes", "image/png")


def test_download_image_returns_none_on_failure():
    client = FakeImageClient({})

    assert download_image("https://x/missing.png", client) is None


def test_download_image_returns_none_for_non_image_content_type():
    # 로그인 리다이렉트로 HTML이 돌아오는 경우 — 추출기에 넘기면 안 된다.
    client = FakeImageClient({"https://x/a.png": FakeImageResponse(b"<html>", "text/html")})

    assert download_image("https://x/a.png", client) is None


def test_download_image_sends_cookie_when_given():
    client = FakeImageClient({"https://x/a.png": FakeImageResponse()})

    download_image("https://x/a.png", client, cookie="NID_AUT=z")

    assert client.calls[0]["headers"]["Cookie"] == "NID_AUT=z"


def test_extract_price_from_images_returns_first_success():
    client = FakeImageClient({
        "https://x/1.png": FakeImageResponse(b"one"),
        "https://x/2.png": FakeImageResponse(b"two"),
    })
    seen = []

    def extractor(image_bytes, mime_type):
        seen.append(image_bytes)
        return 15920 if image_bytes == b"two" else None

    result = extract_price_from_images(["https://x/1.png", "https://x/2.png"], client, extractor)

    assert result == 15920
    assert seen == [b"one", b"two"]


def test_extract_price_from_images_stops_after_first_hit():
    client = FakeImageClient({
        "https://x/1.png": FakeImageResponse(b"one"),
        "https://x/2.png": FakeImageResponse(b"two"),
    })
    seen = []

    def extractor(image_bytes, mime_type):
        seen.append(image_bytes)
        return 15920

    extract_price_from_images(["https://x/1.png", "https://x/2.png"], client, extractor)

    assert seen == [b"one"]  # 첫 성공에서 멈춘다 — 같은 값 중복 저장·불필요한 호출 방지


def test_extract_price_from_images_skips_failed_downloads():
    client = FakeImageClient({"https://x/2.png": FakeImageResponse(b"two")})

    result = extract_price_from_images(
        ["https://x/gone.png", "https://x/2.png"], client, lambda b, m: 15920)

    assert result == 15920


def test_extract_price_from_images_returns_none_when_nothing_found():
    client = FakeImageClient({"https://x/1.png": FakeImageResponse(b"one")})

    assert extract_price_from_images(["https://x/1.png"], client, lambda b, m: None) is None


def test_get_extractor_off_returns_none():
    assert get_extractor("off", api_key="k") is None


def test_get_extractor_gemini_requires_api_key():
    assert get_extractor("gemini", api_key=None) is None
    assert get_extractor("gemini", api_key="k") is not None


def test_get_extractor_ocr_does_not_need_api_key():
    assert get_extractor("ocr", api_key=None) is not None


def test_get_extractor_unknown_name_returns_none():
    assert get_extractor("magic", api_key="k") is None


def test_extract_price_from_images_stops_when_time_budget_is_spent():
    # 실측(2026-09-04): 글 하나의 이미지 분석에서 40초 넘게 머무는 구간이 있었다
    # (이미지 5장 × 다운로드+Gemini). 글당 상한이 없으면 글 수가 늘 때 다시 끊긴다.
    client = FakeImageClient({
        "https://x/1.png": FakeImageResponse(b"one"),
        "https://x/2.png": FakeImageResponse(b"two"),
        "https://x/3.png": FakeImageResponse(b"three"),
    })
    seen = []
    clock = iter([0.0, 30.0, 60.0, 90.0])  # 첫 장 처리에 이미 예산 초과

    def extractor(image_bytes, mime_type):
        seen.append(image_bytes)
        return None

    result = extract_price_from_images(
        ["https://x/1.png", "https://x/2.png", "https://x/3.png"], client, extractor,
        budget_seconds=25.0, now=lambda: next(clock),
    )

    assert result is None
    assert seen == [b"one"]  # 예산 초과 후엔 남은 이미지를 안 본다


def test_extract_price_from_images_always_tries_at_least_one_image():
    # 예산이 0이어도 첫 장은 본다 — 안 그러면 이미지 경로가 통째로 죽는다.
    client = FakeImageClient({"https://x/1.png": FakeImageResponse(b"one")})

    assert extract_price_from_images(
        ["https://x/1.png"], client, lambda b, m: 15920, budget_seconds=0.0,
    ) == 15920


def test_extract_price_from_images_keeps_going_within_budget():
    client = FakeImageClient({
        "https://x/1.png": FakeImageResponse(b"one"),
        "https://x/2.png": FakeImageResponse(b"two"),
    })
    seen = []
    clock = iter([0.0, 1.0, 2.0, 3.0])

    def extractor(image_bytes, mime_type):
        seen.append(image_bytes)
        return 15920 if image_bytes == b"two" else None

    result = extract_price_from_images(
        ["https://x/1.png", "https://x/2.png"], client, extractor,
        budget_seconds=25.0, now=lambda: next(clock),
    )

    assert result == 15920 and seen == [b"one", b"two"]
