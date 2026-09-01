from app.price_extraction import extract_channel_prices, merge_channel_prices_for_display


def test_extracts_single_price_with_explicit_month():
    text = "이마트 7월 29,800원에 샀어요 개꿀"
    result = extract_channel_prices(text, fallback_year_month="2026-01")
    assert result == [{"channel": "이마트", "price_low": 29800, "price_high": 29800, "year_month": "2026-07"}]


def test_extracts_price_range():
    text = "이마트 매장마다 다른데 29,800원~33,000원 정도 하더라구요"
    result = extract_channel_prices(text, fallback_year_month="2026-07")
    assert result == [{"channel": "이마트", "price_low": 29800, "price_high": 33000, "year_month": "2026-07"}]


def test_falls_back_to_post_year_month_when_no_month_mentioned():
    text = "코스트코 19,900원 완전 혜자"
    result = extract_channel_prices(text, fallback_year_month="2026-05")
    assert result == [{"channel": "코스트코", "price_low": 19900, "price_high": 19900, "year_month": "2026-05"}]


def test_emart24_not_misdetected_as_plain_emart():
    text = "이마트24 앱으로 21,000원에 픽업했어요"
    result = extract_channel_prices(text, fallback_year_month="2026-07")
    assert result == [{"channel": "이마트24", "price_low": 21000, "price_high": 21000, "year_month": "2026-07"}]


def test_plain_emart_still_detected_when_not_followed_by_24():
    text = "이마트 가서 29,800원 주고 샀어요"
    result = extract_channel_prices(text, fallback_year_month="2026-07")
    assert result == [{"channel": "이마트", "price_low": 29800, "price_high": 29800, "year_month": "2026-07"}]


def test_multiple_channels_in_one_post():
    text = "이마트 29,800원\n코스트코 25,000원"
    result = extract_channel_prices(text, fallback_year_month="2026-07")
    assert result == [
        {"channel": "이마트", "price_low": 29800, "price_high": 29800, "year_month": "2026-07"},
        {"channel": "코스트코", "price_low": 25000, "price_high": 25000, "year_month": "2026-07"},
    ]


def test_no_channel_or_price_returns_empty_list():
    assert extract_channel_prices("오늘 저녁은 파스타 먹었어요", fallback_year_month="2026-07") == []
    assert extract_channel_prices("이마트 다녀왔어요 좋더라구요", fallback_year_month="2026-07") == []  # 채널만 있고 가격 없음


def test_merge_combines_multiple_sources_into_range():
    rows = [
        {"channel": "이마트", "price_low": 29800, "price_high": 29800, "year_month": "2026-07", "source_url": "https://a"},
        {"channel": "이마트", "price_low": 31000, "price_high": 31000, "year_month": "2026-07", "source_url": "https://b"},
    ]
    merged = merge_channel_prices_for_display(rows)
    assert merged == [{
        "channel": "이마트", "price_low": 29800, "price_high": 31000, "year_month": "2026-07",
        "source_urls": ["https://a", "https://b"],
    }]


def test_merge_uses_most_recent_year_month_when_sources_disagree():
    rows = [
        {"channel": "이마트", "price_low": 29800, "price_high": 29800, "year_month": "2026-05", "source_url": "https://a"},
        {"channel": "이마트", "price_low": 31000, "price_high": 31000, "year_month": "2026-07", "source_url": "https://b"},
    ]
    merged = merge_channel_prices_for_display(rows)
    assert merged[0]["year_month"] == "2026-07"


def test_merge_sorts_by_canonical_channel_order():
    rows = [
        {"channel": "코스트코", "price_low": 1, "price_high": 1, "year_month": "2026-07", "source_url": "https://a"},
        {"channel": "이마트", "price_low": 2, "price_high": 2, "year_month": "2026-07", "source_url": "https://b"},
    ]
    merged = merge_channel_prices_for_display(rows)
    assert [r["channel"] for r in merged] == ["이마트", "코스트코"]  # CHANNEL_ALIASES 순서: 이마트24, 이마트, 코스트코...
