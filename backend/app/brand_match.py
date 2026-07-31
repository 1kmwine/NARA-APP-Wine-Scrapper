from __future__ import annotations
import html
import re

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_ASCII_WORD_CHAR_RE = re.compile(r"[A-Za-z0-9]")
_HANGUL_RE = re.compile(r"[가-힣]")

# 한글은 조사가 띄어쓰기 없이 바로 붙는다("레꼴은", "레꼴이") — 매칭 뒤에 한글이
# 바로 이어지면 실제로는 다른 단어(예: "레꼴" 검색에 "레꼴땅"(Récoltant-Manipulant의
# 한글 표기)이 우연히 걸리는 경우, 실측 2026-07-31)일 수 있다. 뒤에 오는 음절이
# 알려진 조사로 시작하면 진짜 단어 경계로, 아니면 다른 단어의 일부로 본다.
# ponytail: 흔한 조사 목록으로만 판단하는 휴리스틱 — 드문 조사는 놓칠 수 있음.
_KOREAN_JOSA_PREFIXES = (
    "은", "는", "이", "가", "을", "를", "의", "에게", "에서", "한테", "까지", "부터",
    "처럼", "이나", "랑", "으로", "로", "와", "과", "도", "만", "마저", "조차", "밖에", "뿐", "나",
)


def _is_ascii_word_char(ch: str | None) -> bool:
    return ch is not None and bool(_ASCII_WORD_CHAR_RE.match(ch))


def _is_hangul(ch: str | None) -> bool:
    return ch is not None and bool(_HANGUL_RE.match(ch))


def _word_boundary_ok(text: str, start: int, end: int) -> bool:
    before = text[start - 1] if start > 0 else None
    after = text[end] if end < len(text) else None
    if _is_ascii_word_char(before) or _is_ascii_word_char(after):
        return False
    if _is_hangul(after):
        remainder = text[end:end + 3]
        if not any(remainder.startswith(josa) for josa in _KOREAN_JOSA_PREFIXES):
            return False
    return True

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


def fuzzy_find_all(text: str, needle: str):
    """fuzzy_find와 같은 규칙으로, 단어 경계가 유효한 매칭을 전부(제너레이터로)
    돌려준다 — 첫 매칭만으론 부족한 경우(예: 같은 글에 진짜 매칭과 우연히 겹치는
    다른 고유명사가 둘 다 있을 때 나머지 후보도 봐야 하는 경우)에 쓴다."""
    letters = [ch for ch in needle if not ch.isspace()]
    if not letters:
        return
    pattern = re.compile(r"\s*".join(re.escape(ch) for ch in letters), re.IGNORECASE)
    for match in pattern.finditer(text):
        if _word_boundary_ok(text, match.start(), match.end()):
            yield match


def fuzzy_find(text: str, needle: str) -> re.Match | None:
    """대소문자 무시 + 공백 유무 차이를 허용하고 needle을 찾는다. 한글 와인/브랜드명이
    "파니엔테"/"파 니엔테"처럼 표기마다 스페이싱이 다른 경우가 흔해서, 정확한
    부분일치로는 실제로 매칭된 브랜드도 본문에서 못 찾아 하이라이트/요약 센터링이
    조용히 실패하는 문제가 있었다. 단순 부분일치라 "레꼴"이 전혀 다른 단어
    "레꼴땅"(Récoltant-Manipulant) 안에서도 걸리는 문제가 있어(실측 2026-07-31),
    첫 매칭이 아니라 단어 경계가 유효한 첫 매칭을 찾는다."""
    return next(fuzzy_find_all(text, needle), None)


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


# 순수 부분 문자열 매칭은 짧은 브랜드명이 더 큰 단어 안에 우연히 포함될 때
# 오탐을 낸다(2026-07-10 매거진 적재 중 실제로 발견 — "Iter"가 "Writer" 안에서
# 매칭돼 잘못 태깅됨. 2026-07-31 — 한글도 "레꼴"이 "레꼴땅" 안에서 매칭됨).
# 매칭 지점 앞뒤가 유효한 단어 경계일 때만(_word_boundary_ok) 인정한다.
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
            if _word_boundary_ok(lower_text, idx, idx + len(needle)):
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
