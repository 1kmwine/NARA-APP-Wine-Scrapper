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


_ASCII_ONLY_RE = re.compile(r'^[\x00-\x7F]+$')

# 외국 와인명 한글 음역은 표기가 사람마다 갈린다 — 같은 와인을 "프렐루디오/
# 프렐류디오", "샤도네이/사도네이", "까베르네/카베르네", "샤또/샤토"로 적는다
# (실측 2026-09-07). 자모를 거센소리·된소리 → 예사소리, 이중모음 → 단모음으로
# 접어서 이런 변형을 같은 문자열로 만든다. 매칭 판정에만 쓰고 화면 표기는
# 원문 그대로 둔다.
_CHO_FOLD = {
    "ㄲ": "ㄱ", "ㅋ": "ㄱ", "ㄸ": "ㄷ", "ㅌ": "ㄷ", "ㅃ": "ㅂ", "ㅍ": "ㅂ",
    "ㅆ": "ㅅ", "ㅉ": "ㅈ", "ㅊ": "ㅈ",
}
_JUNG_FOLD = {
    "ㅠ": "ㅜ", "ㅛ": "ㅗ", "ㅑ": "ㅏ", "ㅕ": "ㅓ",
    "ㅐ": "ㅔ", "ㅒ": "ㅔ", "ㅖ": "ㅔ", "ㅢ": "ㅣ",
}
_CHO_LIST = list("ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ")
_JUNG_LIST = list("ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ")
_JONG_LIST = ["", *"ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ"]


def fold_translit(text: str) -> str:
    """음역 표기 차이를 접은 문자열을 돌려준다(매칭 비교용)."""
    out = []
    for ch in text or "":
        code = ord(ch) - 0xAC00
        if 0 <= code < 11172:
            cho = _CHO_LIST[code // 588]
            jung = _JUNG_LIST[(code % 588) // 28]
            jong = _JONG_LIST[code % 28]
            cho = _CHO_FOLD.get(cho, cho)
            jung = _JUNG_FOLD.get(jung, jung)
            jong = _CHO_FOLD.get(jong, jong) if jong else jong
            out.append(chr(0xAC00 + _CHO_LIST.index(cho) * 588
                           + _JUNG_LIST.index(jung) * 28 + _JONG_LIST.index(jong)))
        else:
            out.append(ch.lower())
    return "".join(out)


def correct_query_spelling(query: str, catalog_names: list[str]) -> str:
    """검색어의 각 토큰을 상품 카탈로그(integrated_item_info nameKo)에 실제로
    쓰이는 표기로 바꿔준다. 음역 표기가 갈리면 네이버 검색이 아예 다른 글을
    돌려주기 때문이다(실측 2026-09-07 — "프렐류디오 가격"은 유니슨리서치
    프렐류디오 인티앰프 글을, "프렐루디오 가격"은 와인 글을 돌려줬다).

    카탈로그 전체 이름으로 갈아치우지 않고 **토큰 단위로만** 교정한다 —
    "리베라 프렐루디오 넘버원 샤도네이" 같은 긴 정식명으로 검색하면 오히려
    결과가 줄어든다. 매칭되는 카탈로그 토큰이 없으면 입력 그대로 둔다."""
    tokens = (query or "").split()
    if not tokens or not catalog_names:
        return query
    catalog_tokens: dict[str, str] = {}
    for name in catalog_names:
        for token in (name or "").split():
            folded = fold_translit(token)
            # 같은 폴딩 키에 여러 표기가 있으면 먼저 본 것을 쓴다(카탈로그 순서).
            catalog_tokens.setdefault(folded, token)
    corrected = [catalog_tokens.get(fold_translit(t), t) for t in tokens]
    return " ".join(corrected)


def query_tokens_all_present(text: str, query: str) -> bool:
    """검색어의 토큰이 (순서·사이에 낀 단어 무관) 전부 text에 있으면 True.

    구절 그대로 찾는 fuzzy_find만 쓰면 제품명 중간에 다른 단어가 끼는 실제
    표기를 놓친다(실측 2026-09-07 — "프렐루디오 샤도네이" 검색인데 글 제목은
    "리베라 프렐루디오 넘버원 샤도네이"라 매칭 실패, 그래서 이마트 17,800원을
    통째로 놓쳤다). 음역 표기 차이도 fold_translit으로 함께 흡수한다."""
    tokens = [t for t in (query or "").split() if t]
    if not tokens:
        return False
    folded_text = fold_translit(text)
    return all(fuzzy_find(folded_text, fold_translit(token)) for token in tokens)


def flexible_name_match(candidate: str, query: str) -> bool:
    """가격표/영수증에 인쇄된 상품명(candidate)이 검색한 와인(query)과 같은
    제품인지 느슨하게 판정한다. 공백·대소문자는 무시하고, 어느 쪽이 더 긴
    표기여도(예: query "케이머스 나파밸리" vs 가격표 "케이머스 카베르네
    소비뇽 나파밸리") 통과시킨다.

    진열 사진에 가격표가 여러 개 찍힌 경우 모델이 엉뚱한 가격표를 읽는 일이
    있어서(실측 2026-09-05 — 케이머스 진열대 사진에서 아래칸 "꼬르동루즈
    샴페인 51,900원" 가격표를 읽음) 모델이 돌려준 상품명을 코드로 다시
    검증하는 데 쓴다."""
    flat_candidate = re.sub(r'\s+', '', candidate or '').lower()
    flat_query = re.sub(r'\s+', '', query or '').lower()
    if not flat_candidate or not flat_query:
        return False
    if flat_query in flat_candidate or flat_candidate in flat_query:
        return True
    # 첫 토큰(브랜드/생산자명)만 인정한다 — 아무 토큰이나 겹치면 통과시키면
    # "케이머스 나파밸리" 검색에 "나파밸리 카베르네"(다른 나파 와인) 가격표가
    # 통과한다. 산지·품종 토큰은 제품 구분에 쓸 수 없다.
    tokens = query.split()
    brand_token = tokens[0].lower() if tokens else ""
    return len(brand_token) >= 2 and brand_token in flat_candidate


def is_ascii_only(text: str) -> bool:
    """영문 표기 가격표("CAYMUS")인지 판단 — 한글 검색어와는 문자 그대로
    비교가 불가능하므로, 이 경우엔 모델 판정을 신뢰하는 예외를 둔다."""
    return bool(text) and bool(_ASCII_ONLY_RE.match(text))


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
