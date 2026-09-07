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


def test_prompt_names_the_searched_wine_and_forbids_other_products():
    # 실측(2026-09-05): "코스트코 프리미엄 스시콤보 & 로저구라트 까바" 글의
    # 초밥 영수증 49,990원이 로저구라트 코스트코 가격으로 저장됐다 —
    # 프롬프트가 "이 이미지는 와인 결제화면"이라 전제하고 금액만 읽었기 때문.
    client = FakeClient(FakeResponse(_gemini_payload({"final_price": None, "label": None})))

    extract_final_price(b"img", "image/png", api_key="k", client=client, query="로저구라트")

    prompt = client.last_call["json"]["contents"][0]["parts"][0]["text"]
    assert "로저구라트" in prompt
    assert "null" in prompt
    assert "음식" in prompt  # 음식/다른 상품이면 null로 답하라는 지시가 있어야 한다


def test_prompt_without_query_keeps_previous_wording():
    client = FakeClient(FakeResponse(_gemini_payload({"final_price": 15920, "label": "결제 금액"})))

    extract_final_price(b"img", "image/png", api_key="k", client=client)

    prompt = client.last_call["json"]["contents"][0]["parts"][0]["text"]
    assert "와인 구매/결제 화면" in prompt


def test_model_returning_null_for_other_product_yields_none():
    client = FakeClient(FakeResponse(_gemini_payload(
        {"final_price": None, "label": None, "product": "프리미엄 스시콤보 52P"})))

    assert extract_final_price(
        b"img", "image/png", api_key="k", client=client, query="로저구라트") is None


def test_rejects_price_when_tag_name_is_a_different_wine():
    # 실측(2026-09-05): 케이머스 진열대 사진에 가격표가 2개(위 케이머스 144,900원,
    # 아래 꼬르동루즈 샴페인 51,900원) — 모델이 아래 가격표를 읽어 51,900원이
    # 케이머스 코스트코 가격으로 저장됐다. 가격표 상품명을 코드로 재검증한다.
    client = FakeClient(FakeResponse(_gemini_payload({
        "final_price": 51900, "label": "할인행사",
        "matched_name": "꼬르동루즈 샴페인", "matches_target": True,
    })))

    assert extract_final_price(
        b"img", "image/png", api_key="k", client=client, query="케이머스 나파밸리") is None


def test_accepts_price_when_tag_name_matches_the_searched_wine():
    client = FakeClient(FakeResponse(_gemini_payload({
        "final_price": 144900, "label": "가격표",
        "matched_name": "케이머스 카베르네 소비뇽 나파밸리", "matches_target": True,
    })))

    assert extract_final_price(
        b"img", "image/png", api_key="k", client=client, query="케이머스 나파밸리") == 144900


def test_accepts_english_tag_name_trusting_model_judgment():
    # 영문 가격표는 한글 검색어와 문자 비교가 불가능 — 모델 판정을 신뢰한다.
    client = FakeClient(FakeResponse(_gemini_payload({
        "final_price": 144900, "label": "가격표",
        "matched_name": "CAYMUS CABERNET SAUVIGNON", "matches_target": True,
    })))

    assert extract_final_price(
        b"img", "image/png", api_key="k", client=client, query="케이머스 나파밸리") == 144900


def test_rejects_when_model_says_not_target_even_with_a_price():
    client = FakeClient(FakeResponse(_gemini_payload({
        "final_price": 49990, "label": "결제 금액",
        "matched_name": "프리미엄스시콤보 52P", "matches_target": False,
    })))

    assert extract_final_price(
        b"img", "image/png", api_key="k", client=client, query="로저구라트") is None


def test_prompt_warns_about_multiple_price_tags():
    client = FakeClient(FakeResponse(_gemini_payload({"final_price": None})))
    extract_final_price(b"img", "image/png", api_key="k", client=client, query="케이머스 나파밸리")
    prompt = client.last_call["json"]["contents"][0]["parts"][0]["text"]
    assert "가격표가 여러 개" in prompt
    assert "matched_name" in prompt


def test_query_path_requires_name_fields_so_old_style_response_is_rejected():
    # matched_name/matches_target 없이 숫자만 오는 응답은(구 프롬프트 캐시 등)
    # 검증 불가 — 지어내지 않고 버린다.
    client = FakeClient(FakeResponse(_gemini_payload({"final_price": 51900, "label": "가격"})))
    assert extract_final_price(
        b"img", "image/png", api_key="k", client=client, query="케이머스 나파밸리") is None
