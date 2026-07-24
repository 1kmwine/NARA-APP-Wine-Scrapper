#!/usr/bin/env python3
"""docs/briefings/{date}.html(이메일 발송용 정적 브리핑)을 파싱해 docs/data/{date}/*.json
(앱이 실제로 읽는 구조)으로 채운다. docs/data/{date}가 이미 있으면 건너뛴다 — 진짜
스크래핑 데이터를 덮어쓰지 않고, briefings html만 있고 data가 없는 날짜만 백필한다.

실행: backend/.venv/bin/python3 scripts/backfill_docs_data_from_briefings.py
"""
from __future__ import annotations
import json
import re
from pathlib import Path

from bs4 import BeautifulSoup

REPO_ROOT = Path(__file__).resolve().parents[1]
BRIEFINGS_DIR = REPO_ROOT / "docs" / "briefings"
DATA_DIR = REPO_ROOT / "docs" / "data"

# h2 텍스트에 이 라벨이 포함되면 해당 카테고리 — "오늘의 요약"/"Instagram"은
# 스킵(요약은 다른 섹션 재요약이라 중복 집계됨, 인스타는 앱이 아예 안 씀).
SECTION_MAP = {
    "국내 뉴스·매거진": "news",
    "뉴스룸": "newsroom",
    "와쌉 카페": "wassap",
    "YouTube": "youtube",
    "네이버 블로그": "blog",
    "해외": "international",
}
SKIP_HEADERS = ("오늘의 요약", "Instagram")

BRACKET_RE = re.compile(r"^\[([^\]]+)\]\s*(.*)$")


def _section_key(header_text: str) -> str | None:
    for label, key in SECTION_MAP.items():
        if label in header_text:
            return key
    return None


def _title_and_trailing_meta(a_tag):
    """유튜브/블로그 항목은 <a> 안에 날짜·조회수가 별도 <span>으로 붙어있다 —
    분리해서 순수 제목만 돌려준다."""
    span = a_tag.find("span")
    meta = None
    if span is not None:
        meta = span.get_text(strip=True)
        span.extract()
    return a_tag.get_text(strip=True), meta


def parse_briefing_html(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    result = {"news": [], "newsroom": [], "wassap": [], "blog": [], "youtube": {}, "international": []}

    for h2 in soup.find_all("h2"):
        header_text = h2.get_text(strip=True)
        if any(skip in header_text for skip in SKIP_HEADERS):
            continue
        key = _section_key(header_text)
        if key is None:
            continue
        ul = h2.parent.find_next_sibling("ul")
        if ul is None:
            continue

        for li in ul.find_all("li", recursive=False):
            a = li.find("a")
            if a is None:
                continue
            url = a.get("href", "")
            title, meta = _title_and_trailing_meta(a)
            snippet_div = li.find("div")
            snippet = snippet_div.get_text(strip=True) if snippet_div else ""

            if key == "youtube":
                m = BRACKET_RE.match(title)
                channel, video_title = (m.group(1), m.group(2)) if m else ("기타", title)
                result["youtube"].setdefault(channel, []).append({
                    "videoId": "", "title": video_title, "date": meta or "", "views": "", "url": url,
                })
            elif key in ("news", "newsroom"):
                m = BRACKET_RE.match(title)
                press, clean_title = (m.group(1), m.group(2)) if m else ("", title)
                result[key].append({
                    "title": clean_title, "url": url, "snippet": snippet,
                    "press": press, "source": press, "date": "", "age": 0,
                })
            elif key == "wassap":
                result["wassap"].append({
                    "id": "", "title": title, "comments": 0, "url": url, "snippet": snippet, "date": "",
                })
            elif key == "blog":
                result["blog"].append({
                    "title": title, "url": url, "snippet": snippet,
                    "source": "네이버 블로그", "date": meta or "", "age": 0,
                })
            elif key == "international":
                m = BRACKET_RE.match(title)
                source, clean_title = (m.group(1), m.group(2)) if m else ("", title)
                result["international"].append({
                    "title": clean_title, "title_ko": clean_title, "summary_ko": snippet,
                    "source": source, "url": url, "date": "",
                })

    return result


def write_day(date_str: str, parsed: dict) -> None:
    day_dir = DATA_DIR / date_str
    day_dir.mkdir(parents=True, exist_ok=True)
    for cat in ("news", "newsroom", "wassap", "blog"):
        if parsed[cat]:
            (day_dir / f"{cat}.json").write_text(
                json.dumps(parsed[cat], ensure_ascii=False, indent=2), encoding="utf-8")
    if parsed["youtube"]:
        (day_dir / "youtube.json").write_text(
            json.dumps(parsed["youtube"], ensure_ascii=False, indent=2), encoding="utf-8")
    if parsed["international"]:
        intl = {
            "foreign_magazines": parsed["international"],
            "foreign_stats": [], "domestic_stats": [], "events": [], "downstream_market": [],
        }
        (day_dir / "international.json").write_text(
            json.dumps(intl, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    created = []
    for html_path in sorted(BRIEFINGS_DIR.glob("*.html")):
        date_str = html_path.stem
        if (DATA_DIR / date_str).exists():
            print(f"skip {date_str}: docs/data 이미 있음(진짜 스크래핑 데이터 보존)")
            continue
        parsed = parse_briefing_html(html_path.read_text(encoding="utf-8"))
        total = (
            sum(len(parsed[c]) for c in ("news", "newsroom", "wassap", "blog"))
            + sum(len(v) for v in parsed["youtube"].values())
            + len(parsed["international"])
        )
        if total == 0:
            print(f"skip {date_str}: 파싱된 항목 0건")
            continue
        write_day(date_str, parsed)
        created.append((date_str, total))

    print()
    for date_str, total in created:
        print(f"backfilled {date_str}: {total}건")
    print(f"총 {len(created)}일 생성")


if __name__ == "__main__":
    main()
