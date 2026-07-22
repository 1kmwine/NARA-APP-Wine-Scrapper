from app.brand_match import fuzzy_find, make_context_excerpt, make_excerpt, match_brands


def test_make_excerpt_strips_tags_and_whitespace():
    html = "<p>Hello   <b>World</b></p>"
    assert make_excerpt(html) == "Hello World"


def test_make_excerpt_truncates_at_word_boundary():
    text = "단어 " * 150  # 공백 포함 450자
    result = make_excerpt(text, max_length=200)
    assert len(result) <= 200
    assert not result.endswith(" ")


def test_make_excerpt_returns_short_text_unchanged():
    assert make_excerpt("짧은 문장") == "짧은 문장"


def test_make_excerpt_unescapes_html_entities():
    # 네이버 검색 API(블로그 등)는 description에 엔티티를 그대로 남겨 보낸다 —
    # 안 풀면 카드에 "&quot;"가 글자 그대로 노출된다.
    assert make_excerpt("계곡물에 퐁당! &quot;섬세한 기포&quot;") == '계곡물에 퐁당! "섬세한 기포"'


def test_fuzzy_find_matches_needle_with_extra_spacing_in_text():
    # "파니엔테" 검색어인데 본문엔 "파 니엔테"처럼 띄어 쓴 경우가 실제로 흔했다.
    match = fuzzy_find("이 와인은 파 니엔테 샤도네이입니다", "파니엔테")
    assert match is not None
    assert match.group(0) == "파 니엔테"


def test_fuzzy_find_matches_needle_ignoring_case():
    match = fuzzy_find("Roger Goulart Brut", "roger goulart")
    assert match is not None


def test_fuzzy_find_returns_none_when_not_present():
    assert fuzzy_find("전혀 다른 내용", "파니엔테") is None


def test_make_context_excerpt_centers_on_highlight_with_different_spacing():
    text = ("서론 문단이 아주 길게 이어진다 " * 10) + "여기서 파 니엔테 샤도네이를 소개한다 " + ("뒷부분도 길게 이어진다 " * 10)
    result = make_context_excerpt(text, "파니엔테", fallback_excerpt="도입부 요약")
    assert "파 니엔테" in result


def test_make_context_excerpt_centers_on_highlight():
    text = "서론 문단이 아주 길게 이어진다 " * 10 + "여기서 빌까르 살몽 샴페인을 소개한다 " + "뒷부분도 길게 이어진다 " * 10
    result = make_context_excerpt(text, "빌까르 살몽", fallback_excerpt="도입부 요약")
    assert "빌까르 살몽" in result


def test_make_context_excerpt_falls_back_when_highlight_not_found():
    result = make_context_excerpt("전혀 다른 내용", "빌까르 살몽", fallback_excerpt="도입부 요약")
    assert result == "도입부 요약"


def test_make_context_excerpt_falls_back_when_no_highlight_given():
    result = make_context_excerpt("아무 내용", "", fallback_excerpt="도입부 요약")
    assert result == "도입부 요약"


def test_match_brands_finds_exact_word():
    assert match_brands("Montes Alpha is great", ["Montes"]) == ["Montes"]


def test_match_brands_rejects_substring_inside_larger_word():
    # 실제 오탐 사례 재현: 브랜드 "Iter"가 "Writer"라는 흔한 단어 안에 매칭되던 버그
    assert match_brands("Written by our writer", ["Iter"]) == []


def test_match_brands_korean_brand_name_matches():
    assert match_brands("몬테스 와인이 유명하다", ["몬테스"]) == ["몬테스"]


def test_match_brands_dedupes_result():
    assert match_brands("Montes Montes Montes", ["Montes", "Montes"]) == ["Montes"]


def test_match_brands_no_match_returns_empty_list():
    assert match_brands("관련 없는 문장", ["Montes"]) == []


def test_match_brands_finds_match_at_end_of_string():
    assert match_brands("Wine by Montes", ["Montes"]) == ["Montes"]


def test_match_brands_empty_text_returns_empty_list():
    assert match_brands("", ["Montes"]) == []


def test_match_brands_empty_known_brands_returns_empty_list():
    assert match_brands("Montes Alpha", []) == []
