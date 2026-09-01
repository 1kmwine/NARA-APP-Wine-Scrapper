from __future__ import annotations
import re
from datetime import date

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
_PRICE_RE = re.compile(r'(\d{1,3}(?:,\d{3})+|\d{4,6})\s*원')
_MONTH_RE = re.compile(r'(\d{1,2})\s*월')


def _resolve_year_month(line: str, fallback_year_month: str) -> str:
    match = _MONTH_RE.search(line)
    if not match:
        return fallback_year_month
    month = int(match.group(1))
    if not 1 <= month <= 12:
        return fallback_year_month
    today = date.today()
    year = today.year if month <= today.month else today.year - 1
    return f"{year:04d}-{month:02d}"


def extract_channel_prices(body_text: str, fallback_year_month: str) -> list[dict]:
    """정규식 기반 휴리스틱 — 본문에 직접 타이핑된 채널명+가격만 잡는다.
    위젯/이미지 안의 가격, 표현이 크게 다른 문장은 놓칠 수 있음(지어내지 않음:
    채널명과 가격 패턴이 같은 줄에서 둘 다 확인될 때만 결과에 넣는다)."""
    results: list[dict] = []
    for line in body_text.splitlines():
        if not line.strip():
            continue
        prices = [int(p.replace(",", "")) for p in _PRICE_RE.findall(line)]
        if not prices:
            continue
        for channel, pattern in _CHANNEL_PATTERNS.items():
            if not pattern.search(line):
                continue
            results.append({
                "channel": channel,
                "price_low": min(prices),
                "price_high": max(prices),
                "year_month": _resolve_year_month(line, fallback_year_month),
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
