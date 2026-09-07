from __future__ import annotations
import re

from .brand_match import fuzzy_find, query_tokens_all_present

# 순서가 매칭 우선순위다 — "이마트24"를 "이마트"보다 먼저 둬서, 아래 CHANNEL 매칭
# 루프가 "이마트24"를 먼저 확정하면 그 라인에서 "이마트"(plain)는 negative
# lookahead로 걸러진다(둘 다 매칭되는 이중 카운트 방지).
CHANNEL_ALIASES: dict[str, list[str]] = {
    "이마트24": ["이마트24", "이마트 24", "E24", "e24"],
    # "이마트 트레이더스"는 창고형 매장(트레이더스) 한 곳이지 이마트가 아니다 —
    # 24와 같은 방식으로 제외한다(2026-09-04 실측: 한 글에서 이마트·트레이더스로
    # 중복 저장돼 이마트 시세가 오염됐다).
    "이마트": ["이마트몰", "이마트(?!\\s*(?:24|트레이더스))"],
    "코스트코": ["코스트코 홀세일", "코스트코"],
    "트레이더스": ["트레이더스 홀세일", "트레이더스"],
    "롯데마트": ["롯데마트"],
    "CU": ["(?<![A-Za-z])CU(?![A-Za-z])", "씨유"],
    "GS25": ["GS25", "지에스\\s*25"],
    "세븐일레븐": ["세븐일레븐24", "세븐일레븐앱", "세븐일레븐", "7-11"],
    "새마을구판장": ["새마을\\s*구판장"],
    "조양마트": ["조양마트"],
    "레드셀러": ["레드셀러"],
    "와인픽스": ["와인픽스"],
    "에노테카": ["에노테카"],
    "와인앤모어": ["와인\\s*앤\\s*모어"],
}

_CHANNEL_ORDER = list(CHANNEL_ALIASES.keys())
_CHANNEL_PATTERNS = {
    channel: re.compile("|".join(aliases))
    for channel, aliases in CHANNEL_ALIASES.items()
}

# 콤마 그룹(예: 29,800) 또는 4~6자리 순수 숫자(예: 29800) + "원"
_NUM_SRC = r'\d{1,3}(?:,\d{3})+|\d{4,6}'
_PRICE_RE = re.compile(rf'({_NUM_SRC})\s*원')
# 두 숫자가 "~"/"-"/"부터...까지"로 공백만 사이에 두고 바로 이어질 때만 하나의
# 범위 값으로 묶는다 — 그 외(쉼표, "인데", "할인 받아" 같은 말이 낀 경우)는
# 각자 독립된 단일 값이다(가짜 범위 조립 방지, Finding 3).
_RANGE_RE = re.compile(
    rf'(?P<low>{_NUM_SRC})\s*원?\s*(?:~|-|부터)\s*(?P<high>{_NUM_SRC})\s*원\s*(?:까지)?'
)
_MONTH_RE = re.compile(r'(\d{1,2})\s*월')
# "39만원", "39.5만원", "3만9천원" 같은 만/천 단위 표기 — 와쌉 구매글 템플릿에서
# 아주 흔하다(실측 2026-09-05: "- 가격:  39만원", "26만원에 팔길래"). 숫자+원만
# 보던 기존 정규식은 이런 글을 통째로 놓쳤다.
_MANWON_RE = re.compile(r'(?<![\d,])(\d{1,4})(?:\.(\d))?\s*만\s*(?:(\d{1,3})\s*천)?\s*원')
# 만원 표기로 인정할 값의 범위 — 1,000원 미만이나 1천만원 초과는 가격 오인일 확률이 높다.
_MANWON_MIN, _MANWON_MAX = 1_000, 9_999_999
# 면세점/duty free 가격은 국내 채널 시세와 같이 놓을 수 없다(관세·주세 제외 가격).
# 실측 2026-09-05 — 현대면세점 26만원, 에노테카 면세 $187.86 결제화면 글.
_DUTY_FREE_RE = re.compile(r'(면세점|면세|듀티\s*프리|duty\s*free|dfs)', re.IGNORECASE)
# "원"이 생략된 가격 — 목록형 글에서 아주 흔하다(실측 2026-09-07,
# cafe.naver.com/winerack24/241157 "이마트 장터" 목록: "퀘르체토 치냘레 17 82,800
# (이탈리아 토스카나)"). 콤마 그룹만 인정한다 — 빈티지(2019)나 "17" 같은 숫자는
# 콤마가 없어서 걸리지 않는다. 뒤에 다른 단위가 붙은 숫자(1,000ml 등)는 제외.
_BARE_COMMA_NUM_RE = re.compile(
    r'(?<![\d,])(\d{1,3}(?:,\d{3})+)(?!\s*(?:원|ml|mL|ML|㎖|cc|kg|g\b|년|명|개|건|병|km|m\b))'
)
# 장터/행사/특가 가격은 그 채널의 상시 시세와 다르다 — 저장은 하되 화면에서
# 구분 표시한다(사용자 결정 2026-09-07). "할인"만 있는 문구는 너무 흔해서 제외.
_PROMO_RE = re.compile(r'(장터|행사가|행사\s|행사$|특가|세일|프로모션|1\s*\+\s*1|원\s*플러스\s*원)')
# "3만 원 이상 20% 할인", "20만원 이하 상품" 처럼 **조건**으로 쓰인 금액은 가격이
# 아니다(실측 2026-09-07 — 링크카드의 "3만 원 이상"이 이마트 30,000원으로 저장됨).
_THRESHOLD_SUFFIX_RE = re.compile(r'^\s*(?:이상|이하|초과|미만|넘게|이내|부터\s*\d*\s*%)')
# "[📍 로저 구라트, 까바 밀레짐 브뤼 2024]"처럼 한 줄 전체가 대괄호로 싸인 상품
# 섹션 헤더 — 여러 상품을 나열/비교하는 글(레드셀러류 성지 리뷰)의 관례적 표기.
_SECTION_HEADER_RE = re.compile(r'^\[.+\]$')
# "2병 행사가 36,000원 적용 시 한 병당 18,000원"처럼 묶음가와 병당가가 같은 줄에
# 같이 적히는 경우가 흔하다(실측 2026-09-03 GS25 2병 행사 글 — 묶음가 36,000원이
# 병당 가격으로 저장됐다). 병당 가격 표기가 있는 줄에서는 그 값만 후보로 쓴다.
_PER_BOTTLE_RE = re.compile(
    rf'(?:한\s*병\s*(?:당|에)|1\s*병\s*(?:당|에)|병\s*당)\s*[:\-]?\s*(?P<val>{_NUM_SRC})\s*원'
)
# "가격 : 19,990원"처럼 값이 가격임을 라벨로 밝히는 줄. 블로그 스펙블록
# (지역/품종/빈티지/구매처/가격)에서 채널과 가격이 다른 줄로 갈릴 때, 다음 줄을
# 그 채널 가격으로 인정할지 판단하는 근거로 쓴다.
_PRICE_LABEL_RE = re.compile(r'(가격|판매가|구매가|구입가|정가|행사가|결제\s*금액)')
# 라벨조차 없이 가격만 덩그러니 있는 줄("19,990원")도 같은 용도로 인정한다.
_BARE_PRICE_LINE_RE = re.compile(rf'^\s*({_NUM_SRC})\s*원\s*$')
# 내용이 없는 줄 판정 — 네이버 본문엔 zero-width space(​)만 있는 줄이 흔하다.
_BLANKISH_RE = re.compile(r'^[\s​]*$')


def _resolve_year_month(line: str, fallback_year_month: str) -> str:
    """연도 추정은 오늘 날짜(스크레이핑 실행 시점)가 아니라 게시글 자체의
    발행 시점(fallback_year_month)을 기준으로 한다 — 스크레이퍼가 언제
    돌아가든 그건 글 속 가격이 관측된 시점과 무관하다(Finding 4)."""
    match = _MONTH_RE.search(line)
    if not match:
        return fallback_year_month
    month = int(match.group(1))
    if not 1 <= month <= 12:
        return fallback_year_month
    try:
        fallback_year_str, fallback_month_str = fallback_year_month.split("-")
        fallback_year = int(fallback_year_str)
        fallback_month = int(fallback_month_str)
    except (ValueError, AttributeError):
        return fallback_year_month
    year = fallback_year if month <= fallback_month else fallback_year - 1
    return f"{year:04d}-{month:02d}"


def _is_threshold_amount(line: str, match_end: int) -> bool:
    """금액 바로 뒤가 이상/이하/초과/미만이면 가격이 아니라 조건이다."""
    return bool(_THRESHOLD_SUFFIX_RE.match(line[match_end:match_end + 8]))


def _find_price_values(line: str) -> list[dict]:
    """줄에서 가격 값들을 찾는다. `~`/`-`/`부터...까지`로 바로 이어진 두 숫자는
    하나의 범위 값(위치는 그 조합의 시작점)으로, 그 외 숫자는 각각 독립된
    단일 값으로 취급한다."""
    values: list[dict] = []
    consumed: list[tuple[int, int]] = []

    for m in _RANGE_RE.finditer(line):
        low = int(m.group("low").replace(",", ""))
        high = int(m.group("high").replace(",", ""))
        values.append({
            "start": m.start(),
            "price_low": min(low, high),
            "price_high": max(low, high),
        })
        consumed.append((m.start(), m.end()))

    for m in _PRICE_RE.finditer(line):
        if any(start <= m.start() < end for start, end in consumed):
            continue  # 이미 범위로 묶인 숫자 — 단일 값으로 중복 추가하지 않음
        if _is_threshold_amount(line, m.end()):
            continue
        value = int(m.group(1).replace(",", ""))
        values.append({"start": m.start(), "price_low": value, "price_high": value})

    for m in _MANWON_RE.finditer(line):
        if any(start <= m.start() < end for start, end in consumed):
            continue
        man, decimal, cheon = m.group(1), m.group(2), m.group(3)
        value = int(man) * 10_000
        if decimal:
            value += int(decimal) * 1_000
        if cheon:
            value += int(cheon) * 1_000
        if not _MANWON_MIN <= value <= _MANWON_MAX:
            continue
        if _is_threshold_amount(line, m.end()):
            continue
        values.append({"start": m.start(), "price_low": value, "price_high": value})

    for m in _BARE_COMMA_NUM_RE.finditer(line):
        if any(start <= m.start() < end for start, end in consumed):
            continue
        if any(v["start"] == m.start() for v in values):
            continue  # 이미 "원" 붙은 가격으로 잡힌 숫자
        value = int(m.group(1).replace(",", ""))
        if not _MANWON_MIN <= value <= _MANWON_MAX:
            continue
        if _is_threshold_amount(line, m.end()):
            continue
        values.append({"start": m.start(), "price_low": value, "price_high": value})

    # 병당 가격이 명시된 줄이면 묶음가(2병 행사가 등)는 후보에서 빼고 병당가만 쓴다 —
    # 채널별 시세는 병당 가격이어야 비교가 된다.
    per_bottle_starts = {m.start("val") for m in _PER_BOTTLE_RE.finditer(line)}
    if per_bottle_starts:
        per_bottle_values = [v for v in values if v["start"] in per_bottle_starts]
        if per_bottle_values:
            return per_bottle_values

    return values


def line_attributable_to_query(line: str, query: str, section: str | None = None,
                               title: str | None = None) -> bool:
    """가격이 적힌 이 줄이 정말 '검색한 그 와인' 가격인지 판정.

    같은 브랜드의 다른 제품 가격을 검색한 제품 가격으로 붙여버리는 문제가
    실측으로 확인됐다(2026-09-03 — "몬테스 클래식" 검색 결과에 몬테스 알파·
    몬테스 알파 스페셜 퀴베 글의 가격이 클래식 가격으로 저장됨). 판정 규칙:

    - 줄에 검색어가 (띄어쓰기·대소문자 무시) 그대로 있으면 그 와인 가격이다.
    - `section`이 주어지면(글이 [📍 상품명] 섹션 헤더로 여러 상품을 나열하는
      글이라는 뜻 — extract_channel_prices 참고) 줄 자체엔 검색어가 없어도
      그 줄이 속한 섹션 헤더가 검색어를 언급해야만 인정한다. 헤더가 없으면
      (첫 헤더 이전 줄이거나 헤더가 검색어와 무관하면) 버린다 — 완전히 다른
      상품 섹션의 가격이 붙는 걸 막기 위함(2026-09-04 실측 — "로저구라트"
      검색인데 같은 글 속 알마비바·루이나 섹션의 이마트/CU/조양마트 가격이
      붙었다).
    - `section`이 없는(=섹션 헤더가 아예 없는 글) 경우: 검색어도 없고 브랜드
      토큰(검색어 첫 단어)도 없는 줄이면 글 전체 문맥을 따른다 — 글 자체가
      이미 검색어 관련으로 걸러진 상태이고, "이마트에서 19,900원" 처럼
      제품명 없이 가격만 적는 짧은 단일상품 글이 흔하다.
    - 브랜드 토큰만 있고 검색어는 없으면 같은 브랜드의 **다른 제품** 줄이다
      (예: "몬테스 클래식" 검색인데 줄엔 "몬테스 알파 45,000원"). 지어내지
      않기 위해 버린다 — 애매하면 놓치는 쪽.
    """
    if query_tokens_all_present(line, query):
        return True
    if section is not None:
        return query_tokens_all_present(section, query)
    tokens = query.split()
    brand_token = tokens[0] if tokens else ""
    if brand_token and fuzzy_find(line, brand_token):
        return False
    # 가격 줄에 제품명이 전혀 없는 경우("가격: 약 6만원(세븐일레븐 행사가)").
    # 글 문맥을 상속하되, title이 주어지면 제목이 그 와인을 지목해야만 인정한다 —
    # 검색어가 본문에 '언급'으로만 나오는 글(다른 와인 리뷰)에서 그 와인 가격이
    # 검색어 가격으로 붙는 문제가 있었다(실측 2026-09-05 —
    # blog.naver.com/tongtong2you/224358319648 "[레드] 귀달베르토 2022" 글은
    # 사시까이아를 "세컨드 와인"으로만 언급하는데 귀달베르토의 세븐일레븐
    # 6만원이 사시까이아 가격으로 저장됐다).
    if title is not None:
        return query_tokens_all_present(title, query)
    return True


def resolve_single_channel(text: str) -> str | None:
    """글 전체 텍스트에서 채널을 하나로 확정한다. 이미지에서 읽은 가격은 채널
    정보가 없으므로(결제화면에 채널명이 안 찍히는 경우가 많다) 글 텍스트에서
    채널을 정해야 한다.

    채널이 0개거나 2개 이상이면 None — 어느 채널 가격인지 확정할 수 없으면
    저장하지 않는다(기존 '지어내지 않음' 원칙)."""
    found = [channel for channel, pattern in _CHANNEL_PATTERNS.items() if pattern.search(text)]
    return found[0] if len(found) == 1 else None


def _price_from_following_line(lines: list[str], index: int) -> tuple[str, list[dict]] | None:
    """채널만 있고 가격이 없는 줄(lines[index]) 바로 다음 줄에서 그 채널의 가격을
    찾는다. 못 찾으면 None.

    실측(2026-09-04, blog.naver.com/silver0930/224363835611): 블로그 스펙블록은
    "구매처 : 코스트코 일산점" / "가격 : 19,990원"처럼 채널과 가격을 다른 줄에
    적는다. 같은 줄만 보던 기존 로직은 이런 글을 통째로 놓쳤다.

    지어내지 않기 위해 조건을 좁게 잡는다 — 바로 다음(빈 줄 건너뛴) 한 줄만 보고,
    그 줄이 (1) 가격 라벨이 붙었거나 가격만 있는 줄이고, (2) 자기 채널명을 갖고
    있지 않고(그 줄은 그 줄대로 처리되므로 중복 귀속 방지), (3) 가격 값이 정확히
    하나일 때만 인정한다."""
    for following in lines[index + 1:]:
        if _BLANKISH_RE.match(following):
            continue  # 빈 줄/zero-width space 줄은 건너뛴다
        if not (_PRICE_LABEL_RE.search(following) or _BARE_PRICE_LINE_RE.match(following)):
            return None
        if any(pattern.search(following) for pattern in _CHANNEL_PATTERNS.values()):
            return None
        values = _find_price_values(following)
        if len(values) != 1:
            return None  # 가격이 0개면 붙일 게 없고, 2개 이상이면 어느 건지 확정 불가
        return following, values
    return None


def mentions_promo(text: str) -> bool:
    """장터/행사/특가 문맥인지 — 이미지 경로처럼 어느 가격을 읽었는지 코드가 알
    수 없는 경우 글 단위로 판정해 표시 플래그로 남기는 데 쓴다."""
    return bool(_PROMO_RE.search(text or ""))


def mentions_duty_free(text: str) -> bool:
    """면세 문맥인지 — 이미지 경로처럼 어느 가격을 읽었는지 코드가 알 수 없는
    경우 글 단위로 판단해 아예 건너뛰는 데 쓴다."""
    return bool(_DUTY_FREE_RE.search(text or ""))


def _price_from_preceding_line(lines: list[str], index: int) -> tuple[str, list[dict]] | None:
    """채널만 있고 가격이 없는 줄(lines[index]) 바로 앞 줄에서 그 채널의 가격을
    찾는다. 못 찾으면 None.

    실측(2026-09-05, cafe.naver.com/winerack24/369751): 와쌉 구매글 템플릿은
    "- 가격:  39만원" / "- 구입처:  와인픽스 청담점"처럼 가격을 채널보다 **먼저**
    적는다. 다음 줄만 보던 _price_from_following_line으로는 못 잡는다.

    조건은 _price_from_following_line과 같게 좁힌다(지어내지 않기 위해)."""
    for preceding in reversed(lines[:index]):
        if _BLANKISH_RE.match(preceding):
            continue  # 빈 줄/zero-width space 줄은 건너뛴다
        if not (_PRICE_LABEL_RE.search(preceding) or _BARE_PRICE_LINE_RE.match(preceding)):
            return None
        if any(pattern.search(preceding) for pattern in _CHANNEL_PATTERNS.values()):
            return None
        values = _find_price_values(preceding)
        if len(values) != 1:
            return None
        return preceding, values
    return None


def extract_channel_prices(body_text: str, fallback_year_month: str, query: str | None = None,
                           title: str | None = None) -> list[dict]:
    """정규식 기반 휴리스틱 — 본문에 직접 타이핑된 채널명+가격만 잡는다.
    위젯/이미지 안의 가격, 표현이 크게 다른 문장은 놓칠 수 있음(지어내지 않음:
    채널명과 가격 패턴이 같은 줄에서 둘 다 확인될 때만 결과에 넣는다).

    한 줄에 채널이 여러 개 있으면(예: 가격비교표가 한 줄로 뭉개진 경우) 각
    채널은 그 줄의 모든 가격을 다 받는 게 아니라, 문자 위치상 가장 가까운
    가격/범위 하나에만 묶인다(Finding 3 — 그 전엔 같은 줄의 모든 숫자를 풀링해
    모든 채널에 똑같이 붙여서 없는 범위를 지어냈었다).

    query를 주면 같은 브랜드의 다른 제품 가격 줄을 걸러낸다
    (line_attributable_to_query 참고). 글에 [📍 상품명] 형태의 섹션 헤더가
    있으면(여러 상품을 나열/비교하는 글) 가격 줄을 그 직전 헤더에 귀속시켜
    헤더가 검색어와 무관한 섹션의 가격은 버린다.

    채널만 있고 가격이 없는 줄은 바로 다음 줄과 짝지어 본다
    (_price_from_following_line 참고) — 블로그 스펙블록이 "구매처 : 코스트코
    일산점" / "가격 : 19,990원"처럼 줄을 나눠 적는 게 흔하다."""
    results: list[dict] = []
    lines = body_text.splitlines()
    has_sections = any(_SECTION_HEADER_RE.match(ln.strip()) for ln in lines if ln.strip())
    current_section = ""
    # 글 전체에서 채널이 딱 하나면, 채널명이 없는 가격 줄에도 그 채널을 쓸 수 있다.
    post_channel = resolve_single_channel(f"{title or ''}\n{body_text}")
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if _SECTION_HEADER_RE.match(stripped):
            current_section = stripped
            continue
        values = _find_price_values(line)
        # 폴백(글단위 채널 귀속)은 이 줄 자체에 가격이 있을 때만 쓴다 — 옆 줄과
        # 짝지어 얻은 가격까지 폴백에 넘기면 같은 값이 두 번 저장된다(실측:
        # 와쌉 템플릿의 "와인명" 줄이 "가격" 줄과 짝지어지면서 중복 발생).
        values_from_own_line = bool(values)
        attribution_text = line
        if not values:
            # 채널만 있는 줄은 바로 다음 줄, 없으면 바로 앞 줄과 짝지어 본다 —
            # 블로그 스펙블록은 "구매처/가격" 순, 와쌉 구매글 템플릿은
            # "가격/구입처" 순으로 적는다.
            paired = _price_from_following_line(lines, index) or _price_from_preceding_line(lines, index)
            if paired is None:
                continue
            price_line, values = paired
            # 귀속 판정은 채널 줄 + 가격 줄을 함께 본다 — 둘 중 어디에 제품명이
            # 적혀 있든 같은 항목을 가리키기 때문.
            attribution_text = f"{line}\n{price_line}"
        if query:
            section_arg = current_section if has_sections else None
            if not line_attributable_to_query(attribution_text, query, section=section_arg, title=title):
                continue
        year_month = _resolve_year_month(attribution_text, fallback_year_month)
        # 행사가/면세가는 그 채널의 상시 시세와 다르다 — 버리지 않고 표시용
        # 플래그로 남긴다(사용자 결정 2026-09-07). 판정은 가격 줄 문맥 + 제목
        # (장터 목록글은 제목에만 "장터"가 있다).
        flag_text = f"{attribution_text}\n{title or ''}"
        is_promo = bool(_PROMO_RE.search(flag_text))
        is_duty_free = bool(_DUTY_FREE_RE.search(flag_text))
        matched_any_channel = False
        for channel, pattern in _CHANNEL_PATTERNS.items():
            for channel_match in pattern.finditer(line):
                matched_any_channel = True
                nearest = min(values, key=lambda v: abs(channel_match.end() - v["start"]))
                results.append({
                    "channel": channel,
                    "price_low": nearest["price_low"],
                    "price_high": nearest["price_high"],
                    "year_month": year_month,
                    "is_promo": is_promo,
                    "is_duty_free": is_duty_free,
                })
        # 가격 줄에 채널명이 없으면 글 전체에서 채널을 찾는다 — 단 글 전체에
        # 채널이 정확히 하나이고, 이 줄이 검색어를 직접 언급할 때만(사용자 결정
        # 2026-09-07). 실측: "이마트 장터" 목록글은 채널이 제목에만 있고 각 줄은
        # "와인명 가격" 형태다(cafe.naver.com/winerack24/241157).
        if (not matched_any_channel and values_from_own_line and query and post_channel
                and query_tokens_all_present(line, query)):
            nearest = min(values, key=lambda v: v["start"])
            results.append({
                "channel": post_channel,
                "price_low": nearest["price_low"],
                "price_high": nearest["price_high"],
                "year_month": year_month,
                "is_promo": is_promo,
                "is_duty_free": is_duty_free,
            })
    return results


def merge_channel_prices_by_month(rows: list[dict]) -> list[dict]:
    """채널 × 년월 단위로 병합(가격검색 탭 이력 표시용) — 같은 채널·같은 달에
    여러 소스가 있으면 min~max, 출처는 전부 나열. 정렬은 채널(CHANNEL_ALIASES
    순서) → 년월 오름차순 — 시세 추이를 시간순으로 읽을 수 있게."""
    by_key: dict[tuple[str, str], dict] = {}
    for row in rows:
        key = (row["channel"], row["year_month"])
        entry = by_key.get(key)
        # source_type이 "_img"로 끝나면(blog_img/wassap_img) 본문 텍스트가 아니라
        # 이미지에서 읽은 가격이다 — 화면에서 구분 표시하기 위한 플래그.
        is_image_sourced = str(row.get("source_type", "")).endswith("_img")
        if entry is None:
            by_key[key] = {
                "channel": row["channel"],
                "year_month": row["year_month"],
                "price_low": row["price_low"],
                "price_high": row["price_high"],
                "source_urls": [row["source_url"]],
                "via_image": is_image_sourced,
                "promo": bool(row.get("is_promo")),
                "duty_free": bool(row.get("is_duty_free")),
            }
        else:
            entry["price_low"] = min(entry["price_low"], row["price_low"])
            entry["price_high"] = max(entry["price_high"], row["price_high"])
            entry["source_urls"].append(row["source_url"])
            entry["via_image"] = entry["via_image"] or is_image_sourced
            entry["promo"] = entry["promo"] or bool(row.get("is_promo"))
            entry["duty_free"] = entry["duty_free"] or bool(row.get("is_duty_free"))

    def sort_key(key: tuple[str, str]) -> tuple[int, str]:
        channel, year_month = key
        channel_rank = _CHANNEL_ORDER.index(channel) if channel in _CHANNEL_ORDER else len(_CHANNEL_ORDER)
        return (channel_rank, year_month)

    return [by_key[k] for k in sorted(by_key.keys(), key=sort_key)]
