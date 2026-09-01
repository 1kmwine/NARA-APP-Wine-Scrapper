from __future__ import annotations
import re

# 순서가 매칭 우선순위다 — "이마트24"를 "이마트"보다 먼저 둬서, 아래 CHANNEL 매칭
# 루프가 "이마트24"를 먼저 확정하면 그 라인에서 "이마트"(plain)는 negative
# lookahead로 걸러진다(둘 다 매칭되는 이중 카운트 방지).
CHANNEL_ALIASES: dict[str, list[str]] = {
    "이마트24": ["이마트24", "이마트 24", "E24", "e24"],
    "이마트": ["이마트몰", "이마트(?!\\s*24)"],
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
        value = int(m.group(1).replace(",", ""))
        values.append({"start": m.start(), "price_low": value, "price_high": value})

    return values


def extract_channel_prices(body_text: str, fallback_year_month: str) -> list[dict]:
    """정규식 기반 휴리스틱 — 본문에 직접 타이핑된 채널명+가격만 잡는다.
    위젯/이미지 안의 가격, 표현이 크게 다른 문장은 놓칠 수 있음(지어내지 않음:
    채널명과 가격 패턴이 같은 줄에서 둘 다 확인될 때만 결과에 넣는다).

    한 줄에 채널이 여러 개 있으면(예: 가격비교표가 한 줄로 뭉개진 경우) 각
    채널은 그 줄의 모든 가격을 다 받는 게 아니라, 문자 위치상 가장 가까운
    가격/범위 하나에만 묶인다(Finding 3 — 그 전엔 같은 줄의 모든 숫자를 풀링해
    모든 채널에 똑같이 붙여서 없는 범위를 지어냈었다)."""
    results: list[dict] = []
    for line in body_text.splitlines():
        if not line.strip():
            continue
        values = _find_price_values(line)
        if not values:
            continue
        year_month = _resolve_year_month(line, fallback_year_month)
        for channel, pattern in _CHANNEL_PATTERNS.items():
            for channel_match in pattern.finditer(line):
                nearest = min(values, key=lambda v: abs(channel_match.end() - v["start"]))
                results.append({
                    "channel": channel,
                    "price_low": nearest["price_low"],
                    "price_high": nearest["price_high"],
                    "year_month": year_month,
                })
    return results


def merge_channel_prices_for_display(rows: list[dict]) -> list[dict]:
    """채널별로 min~max 병합, 출처는 전부 나열, year_month는 가장 최근 값 사용.
    반환 순서는 CHANNEL_ALIASES 정의 순서를 따른다."""
    by_channel: dict[str, dict] = {}
    for row in rows:
        channel = row["channel"]
        entry = by_channel.get(channel)
        if entry is None:
            by_channel[channel] = {
                "channel": channel,
                "price_low": row["price_low"],
                "price_high": row["price_high"],
                "year_month": row["year_month"],
                "source_urls": [row["source_url"]],
            }
        else:
            entry["price_low"] = min(entry["price_low"], row["price_low"])
            entry["price_high"] = max(entry["price_high"], row["price_high"])
            if row["year_month"] > entry["year_month"]:
                entry["year_month"] = row["year_month"]
            entry["source_urls"].append(row["source_url"])
    return [by_channel[c] for c in _CHANNEL_ORDER if c in by_channel]
