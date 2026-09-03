import json

from app.price_image_gemini import extract_final_price


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def _gemini_payload(obj: dict) -> dict:
    return {"candidates": [{"content": {"parts": [{"text": json.dumps(obj)}]}}]}


class FakeClient:
    def __init__(self, response):
        self._response = response
        self.last_call = None

    def post(self, url, *, params=None, json=None, timeout=None):
        self.last_call = {"url": url, "params": params, "json": json}
        return self._response


def test_extract_final_price_reads_final_payment_amount():
    client = FakeClient(FakeResponse(_gemini_payload({"final_price": 15920, "label": "최종 결제 금액"})))

    assert extract_final_price(b"img", "image/png", api_key="k", client=client) == 15920


def test_extract_final_price_sends_image_inline_with_json_mime():
    client = FakeClient(FakeResponse(_gemini_payload({"final_price": 15920, "label": "결제 금액"})))

    extract_final_price(b"img-bytes", "image/jpeg", api_key="k", client=client)

    parts = client.last_call["json"]["contents"][0]["parts"]
    assert parts[1]["inlineData"]["mimeType"] == "image/jpeg"
    assert parts[1]["inlineData"]["data"]  # base64 인코딩된 값이 실려야 한다
    assert client.last_call["json"]["generationConfig"]["responseMimeType"] == "application/json"
    assert client.last_call["params"] == {"key": "k"}


def test_extract_final_price_returns_none_when_model_finds_no_price():
    client = FakeClient(FakeResponse(_gemini_payload({"final_price": None, "label": None})))

    assert extract_final_price(b"img", "image/png", api_key="k", client=client) is None


def test_extract_final_price_returns_none_on_http_error():
    # 무료 티어에서 429/503이 드물지 않다 — 이 이미지만 스킵하고 검색은 계속돼야 하므로
    # 예외를 밖으로 던지지 않는다.
    client = FakeClient(FakeResponse({}, status_code=503))

    assert extract_final_price(b"img", "image/png", api_key="k", client=client) is None


def test_extract_final_price_returns_none_on_malformed_response():
    client = FakeClient(FakeResponse({"candidates": []}))

    assert extract_final_price(b"img", "image/png", api_key="k", client=client) is None


def test_extract_final_price_returns_none_on_non_integer_value():
    client = FakeClient(FakeResponse(_gemini_payload({"final_price": "열다섯", "label": "?"})))

    assert extract_final_price(b"img", "image/png", api_key="k", client=client) is None
