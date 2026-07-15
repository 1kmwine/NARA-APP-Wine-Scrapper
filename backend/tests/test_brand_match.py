from app.brand_match import make_excerpt, match_brands


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
