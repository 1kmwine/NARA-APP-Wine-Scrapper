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


def test_parse_article_meta_truncates_long_thumbnail_url_to_500_chars():
    # thumbnail_path 컬럼이 VARCHAR(500) — CDN 서명 URL이 긴 사이트에서
    # INSERT가 깨지지 않도록 title/excerpt와 동일하게 방어해야 한다.
    long_url = "https://cdn.example.com/" + ("a" * 600)
    html = f'<html><head><meta property="og:image" content="{long_url}"></head><body></body></html>'
    parsed = parse_article_meta(html, fallback_title="제목")
    assert len(parsed.thumbnail_url) == 500


def test_extract_visible_text_strips_script_and_style():
    html = "<html><body><script>var x=1;</script><style>.a{}</style><p>보이는 텍스트</p></body></html>"
    assert extract_visible_text(html) == "보이는 텍스트"


def test_parse_article_meta_handles_truncated_malformed_html():
    # head의 meta 태그 자체는 온전히 닫혀 있지만(실제 스크레이핑에서 head는 문서
    # 초반부라 온전히 도착하는 경우가 대부분), 문서 전체는 </body></html> 없이
    # 잘린 형태 — 네트워크 중단으로 응답이 잘려 들어올 때 실제로 나타나는 모양.
    # lxml 6.x(libxml2 상향)는 5.x보다 엄격해져서 태그 자체가 안 닫힌 경우(예:
    # `content="제목"` 뒤에 `>`가 아예 없는 경우)는 더 이상 복구하지 못하지만,
    # 이 케이스처럼 태그 자체는 닫혀 있고 그 뒤 문서만 잘린 경우는 여전히 정상
    # 복구되므로 예외 없이 og:title을 읽어야 한다.
    html = '<html><head><meta property="og:title" content="제목"></head><body><p>본문이 여기서 잘림'
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
