from app.parse import parse_article_meta, extract_visible_text


OG_HTML = """
<html><head>
<meta property="og:title" content="몬테스 알파 새 빈티지 출시">
<meta property="og:description" content="칠레 와이너리 몬테스가 새 빈티지를 출시했다.">
<meta property="og:image" content="https://example.com/thumb.jpg">
<meta property="article:published_time" content="2026-07-01T09:00:00+09:00">
</head><body><p>본문 내용입니다.</p></body></html>
"""


def test_parse_article_meta_reads_og_tags():
    parsed = parse_article_meta(OG_HTML, fallback_title="fallback")
    assert parsed.title == "몬테스 알파 새 빈티지 출시"
    assert "몬테스" in parsed.excerpt
    assert parsed.thumbnail_url == "https://example.com/thumb.jpg"
    assert parsed.published_date == "2026-07-01"


def test_parse_article_meta_falls_back_to_title_and_body_text():
    html = "<html><body><p>og 태그가 없는 페이지</p></body></html>"
    parsed = parse_article_meta(html, fallback_title="대체 제목")
    assert parsed.title == "대체 제목"
    assert "og 태그가 없는 페이지" in parsed.excerpt


def test_parse_article_meta_rejects_non_iso_date():
    html = (
        '<html><head><meta property="article:published_time" '
        'content="Thu, 21 May 2026 00:00:00 GMT"></head><body></body></html>'
    )
    parsed = parse_article_meta(html, fallback_title="제목")
    assert parsed.published_date is None


def test_parse_article_meta_truncates_long_title_to_500_chars():
    long_title = "가" * 600
    html = f'<html><head><meta property="og:title" content="{long_title}"></head><body></body></html>'
    parsed = parse_article_meta(html, fallback_title="제목")
    assert len(parsed.title) == 500


def test_extract_visible_text_strips_script_and_style():
    html = "<html><body><script>var x=1;</script><style>.a{}</style><p>보이는 텍스트</p></body></html>"
    assert extract_visible_text(html) == "보이는 텍스트"


def test_parse_article_meta_handles_truncated_malformed_html():
    # 닫는 태그가 하나도 없는, 실제 스크레이핑 중 잘려서 들어올 수 있는 형태의 HTML.
    # html.parser보다 관대한 lxml 파서로 교체했으므로 예외 없이 og:title을 읽어야 한다.
    html = '<html><head><meta property="og:title" content="제목"'
    parsed = parse_article_meta(html, fallback_title="fallback")
    assert parsed.title == "제목"


def test_extract_visible_text_handles_truncated_malformed_html():
    html = '<html><head><meta property="og:title" content="제목"'
    # 예외 없이 문자열을 반환하기만 하면 된다 (내용 자체는 비어있어도 무방).
    result = extract_visible_text(html)
    assert isinstance(result, str)


def test_parse_article_meta_thumbnail_is_none_when_og_image_missing():
    html = "<html><head></head><body><p>이미지 태그 없음</p></body></html>"
    parsed = parse_article_meta(html, fallback_title="제목")
    assert parsed.thumbnail_url is None


def test_parse_article_meta_thumbnail_is_none_when_og_image_whitespace_only():
    html = '<html><head><meta property="og:image" content="   "></head><body></body></html>'
    parsed = parse_article_meta(html, fallback_title="제목")
    assert parsed.thumbnail_url is None
