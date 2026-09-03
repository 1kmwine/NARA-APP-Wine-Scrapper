from app.price_image_ocr import parse_price_from_ocr_text


def test_parses_price_on_the_same_line_as_label():
    assert parse_price_from_ocr_text("최종 결제 금액 15,920원") == 15920


def test_parses_price_on_the_line_after_label():
    # 결제화면은 라벨과 금액이 좌우로 떨어져 있어 OCR에서 줄이 갈리는 경우가 많다.
    text = "최종 결제 금액\n15,920원\n포인트 적립 16P"
    assert parse_price_from_ocr_text(text) == 15920


def test_prefers_final_payment_over_total_product_amount():
    # 총 상품 금액(정가)과 최종 결제금액이 같이 찍힌 결제화면 — 결제금액을 쓴다.
    text = "총 상품 금액 19,900원\n할인금액 -3,980원\n최종 결제 금액 15,920원"
    assert parse_price_from_ocr_text(text) == 15920


def test_tolerates_ocr_separator_noise():
    # OCR이 쉼표를 마침표/공백으로 잘못 읽는 경우가 흔하다.
    assert parse_price_from_ocr_text("최종 결제 금액 15.920 원") == 15920
    assert parse_price_from_ocr_text("결제 금액 15 920원") == 15920


def test_returns_none_when_no_payment_label():
    # 라벨이 없으면 '가장 큰 숫자'식 추측을 하지 않는다 — 지어내지 않음.
    assert parse_price_from_ocr_text("와인 사진입니다 2026년 9월") is None


def test_returns_none_when_label_has_no_number_nearby():
    assert parse_price_from_ocr_text("최종 결제 금액\n확인 중") is None
