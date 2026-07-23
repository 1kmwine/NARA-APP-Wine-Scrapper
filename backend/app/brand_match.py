from __future__ import annotations
import html
import re

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_ASCII_WORD_CHAR_RE = re.compile(r"[A-Za-z0-9]")

# match_brands는 외부 웹사이트에서 스크래핑한 임의의 텍스트를 그대로 받으므로,
# 반복 문자로만 이루어진 병리적 입력(광고 필러, 압축 안 된 minified 블롭 등)에서
# 거부 루프가 O(n^2)로 느려지는 것을 막기 위해 검색 대상 길이를 상한선으로 자른다.
_MAX_MATCH_TEXT_LENGTH = 50_000


def make_excerpt(html_or_text: str, max_length: int = 200) -> str:
    # 네이버 검색 API(블로그 등)는 description에 &quot; 같은 HTML 엔티티를 문자
    # 그대로 남겨서 반환한다 — 안 풀면 카드에 "&quot;"가 글자 그대로 노출된다.
    text = html.unescape(html_or_text)
    text = _TAG_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text).strip()
    if len(text) <= max_length:
        return text
    truncated = text[:max_length]
    last_space = truncated.rfind(" ")
    return (truncated[:last_space] if last_space > 0 else truncated).strip()


def fuzzy_find(text: str, needle: str) -> re.Match | None:
    """대소문자 무시 + 공백 유무 차이를 허용하고 needle을 찾는다. 한글 와인/브랜드명이
    "파니엔테"/"파 니엔테"처럼 표기마다 스페이싱이 다른 경우가 흔해서, 정확한
    부분일치로는 실제로 매칭된 브랜드도 본문에서 못 찾아 하이라이트/요약 센터링이
    조용히 실패하는 문제가 있었다."""
    letters = [ch for ch in needle if not ch.isspace()]
    if not letters:
        return None
    pattern = r"\s*".join(re.escape(ch) for ch in letters)
    return re.search(pattern, text, re.IGNORECASE)


def make_context_excerpt(full_text: str, highlight: str, fallback_excerpt: str, window: int = 90) -> str:
    """검색어/매칭된 브랜드가 실제로 등장하는 위치를 중심으로 요약을 만든다.
    og:description(기사 도입부)엔 매칭된 브랜드가 아예 안 나오는 경우가 흔해서
    (예: '올해의 샴페인 브랜드 TOP10' 기사의 도입부는 특정 브랜드를 언급하지 않음),
    카드에 왜 이 결과가 매칭됐는지 보이지 않는 문제가 있었다."""
    if not highlight:
        return fallback_excerpt
    match = fuzzy_find(full_text, highlight)
    if not match:
        return fallback_excerpt
    start = max(0, match.start() - window)
    end = min(len(full_text), match.end() + window)
    if start == 0 and end == len(full_text):
        # 앞뒤로 잘라낼 게 없다 — full_text가 제목(+빈 excerpt)뿐이라 "문맥"이라
        # 부를 본문이 없다(예: 와쌉 검색 결과에 본문 snippet을 못 구한 글). 이럴 땐
        # 제목을 그대로 되풀이하는 대신 원래 excerpt(비어 있을 수도 있음)를 쓴다.
        return fallback_excerpt
    return make_excerpt(full_text[start:end])


def _is_ascii_word_char(ch: str | None) -> bool:
    return ch is not None and bool(_ASCII_WORD_CHAR_RE.match(ch))


# 순수 부분 문자열 매칭은 짧은 브랜드명이 더 큰 영단어 안에 우연히 포함될 때
# 오탐을 낸다(2026-07-10 매거진 적재 중 실제로 발견 — "Iter"가 "Writer" 안에서
# 매칭돼 잘못 태깅됨). 매칭 지점 앞뒤 글자가 ASCII 영숫자가 아닐 때만
# (한글/공백/문장부호/문자열 경계는 전부 허용) 유효한 매칭으로 인정한다.
# scripts/lib/article-shared.ts의 matchBrands를 그대로 이식.
def match_brands(text: str, known_brands: list[str]) -> list[str]:
    if len(text) > _MAX_MATCH_TEXT_LENGTH:
        text = text[:_MAX_MATCH_TEXT_LENGTH]
    lower_text = text.lower()
    matched: list[str] = []
    for brand in known_brands:
        needle = brand.lower()
        if not needle:
            continue
        idx = lower_text.find(needle)
        found = False
        while idx != -1:
            before = lower_text[idx - 1] if idx > 0 else None
            after_pos = idx + len(needle)
            after = lower_text[after_pos] if after_pos < len(lower_text) else None
            if not _is_ascii_word_char(before) and not _is_ascii_word_char(after):
                found = True
                break
            idx = lower_text.find(needle, idx + 1)
        if found:
            matched.append(brand)

    seen: set[str] = set()
    result: list[str] = []
    for b in matched:
        if b not in seen:
            seen.add(b)
            result.append(b)
    return result
