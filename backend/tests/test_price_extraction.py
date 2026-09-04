from app.price_extraction import extract_channel_prices, merge_channel_prices_by_month


def test_extracts_single_price_with_explicit_month():
    # fallback_year_month는 글의 발행 시점(2026-07)이다 — "7월"은 그 발행 월
    # 자신을 가리키므로 같은 해로 resolve돼야 한다(Finding 4: 오늘 날짜가 아니라
    # 글 발행 시점 기준).
    text = "이마트 7월 29,800원에 샀어요 개꿀"
    result = extract_channel_prices(text, fallback_year_month="2026-07")
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


def test_multiple_channels_same_line_bind_to_nearest_price_not_pooled():
    text = "이마트 29,800원, 코스트코 19,900원 이었어요"
    result = extract_channel_prices(text, fallback_year_month="2026-07")
    # 이마트 must get ONLY 29800 (its nearest price), 코스트코 must get ONLY 19900
    by_channel = {r["channel"]: r for r in result}
    assert by_channel["이마트"]["price_low"] == 29800
    assert by_channel["이마트"]["price_high"] == 29800
    assert by_channel["코스트코"]["price_low"] == 19900
    assert by_channel["코스트코"]["price_high"] == 19900


def test_unconnected_second_number_does_not_form_fake_range():
    text = "와인앤모어 129,000원인데 배송비 3,000원 별도"
    result = extract_channel_prices(text, fallback_year_month="2026-07")
    assert result == [{"channel": "와인앤모어", "price_low": 129000, "price_high": 129000, "year_month": "2026-07"}]


def test_existing_range_with_explicit_connector_still_works():
    # regression: the ORIGINAL range-detection behavior (Task 1) must still work
    text = "이마트 매장마다 다른데 29,800원~33,000원 정도 하더라구요"
    result = extract_channel_prices(text, fallback_year_month="2026-07")
    assert result == [{"channel": "이마트", "price_low": 29800, "price_high": 33000, "year_month": "2026-07"}]


def test_range_connected_via_buteo_kkaji_still_forms_one_range():
    text = "이마트 29,800원부터 33,000원까지 다양해요"
    result = extract_channel_prices(text, fallback_year_month="2026-07")
    assert result == [{"channel": "이마트", "price_low": 29800, "price_high": 33000, "year_month": "2026-07"}]


def test_comparison_table_collapsed_to_one_line_binds_each_channel_correctly():
    # Smart Editor 비교표가 한 줄로 뭉개진 경우 — 실제로 자주 나오는 형태.
    text = "이마트 29,800원 코스트코 19,900원 롯데마트 21,000원"
    result = extract_channel_prices(text, fallback_year_month="2026-07")
    by_channel = {r["channel"]: r for r in result}
    assert by_channel["이마트"]["price_low"] == 29800
    assert by_channel["코스트코"]["price_low"] == 19900
    assert by_channel["롯데마트"]["price_low"] == 21000


def test_year_resolves_relative_to_post_date_not_scrape_date():
    result = extract_channel_prices("이마트 7월에 29,800원 이었음", fallback_year_month="2024-07")
    assert result[0]["year_month"] == "2024-07"


def test_future_month_relative_to_post_date_implies_prior_year():
    result = extract_channel_prices("이마트에서 12월 한정 할인, 지금은 29,800원", fallback_year_month="2024-03")
    assert result[0]["year_month"] == "2023-12"


def test_per_bottle_price_wins_over_bundle_price_on_same_line():
    # 실측(2026-09-03 GS25 2병 행사 글): 묶음가 36,000원이 병당 가격으로 저장됐다.
    text = "편의점 구매 시(GS25편의점 기준) : 2병 행사가 36,000원 적용 시 한 병당 18,000원"
    result = extract_channel_prices(text, fallback_year_month="2026-07")
    assert result == [{"channel": "GS25", "price_low": 18000, "price_high": 18000, "year_month": "2026-07"}]


def test_per_bottle_variants_are_recognized():
    for text in (
        "이마트 2병 49,000원, 1병당 24,500원",
        "이마트 2병 49,000원, 병당 24,500원",
        "이마트 2병에 49,000원 → 한 병에 24,500원",
    ):
        result = extract_channel_prices(text, fallback_year_month="2026-07")
        assert result[0]["price_low"] == 24500, text


def test_line_without_per_bottle_marker_keeps_all_values():
    # 병당 표기가 없으면 기존 동작 그대로 — 가장 가까운 값에 묶인다.
    text = "이마트 29,800원"
    result = extract_channel_prices(text, fallback_year_month="2026-07")
    assert result == [{"channel": "이마트", "price_low": 29800, "price_high": 29800, "year_month": "2026-07"}]


def test_merge_by_month_combines_multiple_sources_in_same_month_into_range():
    rows = [
        {"channel": "이마트", "price_low": 29800, "price_high": 29800, "year_month": "2026-07", "source_url": "https://a"},
        {"channel": "이마트", "price_low": 31000, "price_high": 31000, "year_month": "2026-07", "source_url": "https://b"},
    ]
    merged = merge_channel_prices_by_month(rows)
    assert merged == [{
        "channel": "이마트", "year_month": "2026-07", "price_low": 29800, "price_high": 31000,
        "source_urls": ["https://a", "https://b"], "via_image": False,
    }]


def test_merge_by_month_flags_image_sourced_rows():
    # 화면에서 이미지(OCR/Gemini) 추출 가격을 텍스트 추출과 구분 표시하기 위한 플래그.
    rows = [{"channel": "GS25", "price_low": 15920, "price_high": 15920, "year_month": "2026-08",
              "source_url": "https://a", "source_type": "wassap_img"}]
    merged = merge_channel_prices_by_month(rows)
    assert merged[0]["via_image"] is True


def test_merge_by_month_flags_mixed_month_as_image_if_any_row_is():
    # 같은 채널·같은 달에 텍스트 추출 값과 이미지 추출 값이 섞이면, 이미지가
    # 하나라도 기여했으면 표시한다 — 어느 쪽인지 몰라도 "확인 필요" 신호로 충분.
    rows = [
        {"channel": "GS25", "price_low": 15000, "price_high": 15000, "year_month": "2026-08",
         "source_url": "https://a", "source_type": "wassap"},
        {"channel": "GS25", "price_low": 15920, "price_high": 15920, "year_month": "2026-08",
         "source_url": "https://b", "source_type": "wassap_img"},
    ]
    merged = merge_channel_prices_by_month(rows)
    assert merged[0]["via_image"] is True


def test_merge_by_month_keeps_different_months_as_separate_rows():
    rows = [
        {"channel": "이마트", "price_low": 29800, "price_high": 29800, "year_month": "2026-05", "source_url": "https://a"},
        {"channel": "이마트", "price_low": 31000, "price_high": 31000, "year_month": "2026-07", "source_url": "https://b"},
    ]
    merged = merge_channel_prices_by_month(rows)
    assert [ (r["year_month"], r["price_low"]) for r in merged ] == [("2026-05", 29800), ("2026-07", 31000)]


def test_merge_by_month_sorts_by_canonical_channel_order_then_month():
    rows = [
        {"channel": "코스트코", "price_low": 1, "price_high": 1, "year_month": "2026-07", "source_url": "https://a"},
        {"channel": "이마트", "price_low": 2, "price_high": 2, "year_month": "2026-08", "source_url": "https://c"},
        {"channel": "이마트", "price_low": 2, "price_high": 2, "year_month": "2026-07", "source_url": "https://b"},
    ]
    merged = merge_channel_prices_by_month(rows)
    assert [(r["channel"], r["year_month"]) for r in merged] == [
        ("이마트", "2026-07"), ("이마트", "2026-08"), ("코스트코", "2026-07"),
    ]


from app.price_extraction import resolve_single_channel


def test_resolve_single_channel_returns_the_only_channel():
    assert resolve_single_channel("GS25 오늘의 와인 - 베터하프 문의") == "GS25"


def test_resolve_single_channel_returns_none_when_no_channel():
    assert resolve_single_channel("베터하프 마셔봤어요 맛있네요") is None


def test_resolve_single_channel_returns_none_when_ambiguous():
    # 채널이 둘 이상이면 이미지 속 가격이 어느 채널 것인지 확정할 수 없다 —
    # 지어내지 않고 버린다.
    assert resolve_single_channel("이마트랑 GS25 둘 다 가봤는데") is None


def test_resolve_single_channel_does_not_double_count_emart24():
    # "이마트24"는 "이마트" 패턴에 negative lookahead가 걸려 있어 한 채널로만 잡힌다.
    assert resolve_single_channel("이마트24에서 봤어요") == "이마트24"


def test_extract_channel_prices_ignores_other_products_sections_when_headers_present():
    # 실측(2026-09-04): "로저구라트" 검색인데 같은 글(레드셀러류 다품목 비교 리뷰,
    # [📍 상품명] 섹션 헤더로 상품이 나뉜다) 속 완전히 다른 상품(알마비바) 섹션의
    # 이마트 가격이 붙었다 — 브랜드 토큰 충돌이 없어서 기존 line_attributable_to_query가
    # 못 걸렀다. 섹션 헤더가 검색어를 언급하는 섹션의 가격만 인정해야 한다.
    text = (
        "[📍 알마비바 2022]\n"
        "지난 5월 이마트 장터에서 249,800원.\n"
        "\n"
        "[📍 로저 구라트, 까바 밀레짐 브뤼 2024]\n"
        "조양마트에서 21,000원에 봤어요.\n"
    )
    result = extract_channel_prices(text, fallback_year_month="2026-08", query="로저구라트")
    assert [(r["channel"], r["price_low"]) for r in result] == [("조양마트", 21000)]


def test_extract_channel_prices_without_section_headers_keeps_old_behavior():
    # 섹션 헤더가 아예 없는 글은 기존 전역 문맥 판정을 그대로 쓴다(회귀 방지).
    text = "이마트에서 19,900원에 샀어요"
    result = extract_channel_prices(text, fallback_year_month="2026-08", query="몬테스 클래식")
    assert result == [{"channel": "이마트", "price_low": 19900, "price_high": 19900, "year_month": "2026-08"}]


def test_extract_channel_prices_pairs_channel_line_with_next_line_price():
    # 실측(2026-09-04, blog.naver.com/silver0930/224363835611): 블로그 스펙블록은
    # "구매처 : 코스트코 일산점" / "가격 : 19,990원"처럼 채널과 가격이 다른 줄에 적힌다.
    # 같은 줄만 보던 기존 로직은 이걸 통째로 놓쳤다.
    text = (
        "지역 : 스페인-카탈루냐\n"
        "수입사 : 나라셀라(주)\n"
        "구매처 : 코스트코 일산점\n"
        "가격 : 19,990원\n"
    )
    result = extract_channel_prices(text, fallback_year_month="2026-07", query="로저구라트")
    assert [(r["channel"], r["price_low"], r["price_high"]) for r in result] == [("코스트코", 19990, 19990)]


def test_extract_channel_prices_pairs_with_bare_price_line():
    # 라벨 없이 가격만 있는 줄도 붙인다.
    text = "구매처 : 이마트\n29,800원\n"
    result = extract_channel_prices(text, fallback_year_month="2026-07")
    assert [(r["channel"], r["price_low"]) for r in result] == [("이마트", 29800)]


def test_extract_channel_prices_does_not_pair_unrelated_next_line():
    # 다음 줄이 가격 라벨도 아니고 가격만 있는 줄도 아니면 붙이지 않는다 — 지어내지 않음.
    text = "코스트코에서 부담 없는 스파클링 찾는 분\n이 와인은 30,000원짜리 안주와 잘 어울린다\n"
    result = extract_channel_prices(text, fallback_year_month="2026-07")
    assert result == []


def test_extract_channel_prices_does_not_pair_when_next_line_has_own_channel():
    # 다음 줄에 자기 채널이 있으면 그 줄은 그 줄대로 처리된다(중복 귀속 방지).
    text = "구매처 : 코스트코\n이마트 가격 : 29,800원\n"
    result = extract_channel_prices(text, fallback_year_month="2026-07")
    assert [(r["channel"], r["price_low"]) for r in result] == [("이마트", 29800)]


def test_extract_channel_prices_skips_ambiguous_multi_price_next_line():
    # 다음 줄에 가격이 여러 개면 어느 게 그 채널 값인지 확정 못 하므로 버린다.
    text = "구매처 : 코스트코\n가격 : 19,990원 / 정가 29,900원\n"
    result = extract_channel_prices(text, fallback_year_month="2026-07")
    assert result == []
