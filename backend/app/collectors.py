from __future__ import annotations
import json
import re
from dataclasses import dataclass
from datetime import date, timedelta

from .brand_match import make_excerpt


@dataclass(frozen=True)
class CollectedItem:
    title: str
    excerpt: str
    thumbnail_url: str | None
    external_url: str
    published_date: str | None
    source_name: str


def _build_item(title: str, excerpt: str, thumbnail_url: str | None, external_url: str,
                 published_date: str | None, source_name: str) -> CollectedItem:
    return CollectedItem(
        title=(title or "").strip()[:500],
        excerpt=make_excerpt(excerpt or ""),
        thumbnail_url=thumbnail_url,
        external_url=external_url,
        published_date=published_date,
        source_name=source_name,
    )


# ─────────────────────────── 날짜 유틸 (WINE-BRIEFING/scrape.py의 age_days 포팅) ───────────────────────────
_DAYS_AGO_RE = re.compile(r'(\d+)\s*일\s*전')
_WEEKS_AGO_RE = re.compile(r'(\d+)\s*주\s*전')
_RECENT_RE = re.compile(r'\d+\s*[분초시간]\s*전|이내')
_ABS_DATE_RE = re.compile(r'(\d{4})[.\-](\d{1,2})[.\-](\d{1,2})')


def _relative_age_days(text: str) -> int | None:
    if not text:
        return None
    if _RECENT_RE.search(text):
        return 0
    match = _DAYS_AGO_RE.search(text)
    if match:
        return int(match.group(1))
    match = _WEEKS_AGO_RE.search(text)
    if match:
        return int(match.group(1)) * 7
    match = _ABS_DATE_RE.search(text)
    if match:
        try:
            parsed = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
            return (date.today() - parsed).days
        except ValueError:
            return None
    return None


def _relative_date_to_iso(text: str) -> str | None:
    age = _relative_age_days(text)
    if age is None:
        return None
    return (date.today() - timedelta(days=age)).isoformat()


# ─────────────────────────── 유튜브 (scrape_youtube 포팅) ───────────────────────────
_YT_INITIAL_DATA_RE = re.compile(r'var ytInitialData\s*=\s*(\{.+?\});\s*</script>', re.DOTALL)
_CHANNEL_ID_RE = re.compile(r'"channelId":"(UC[\w-]{22})"')


def resolve_channel_id(handle: str, client) -> str:
    """핸들 페이지에서 Channel ID를 추출한다. main.py의 소스 추가 폼(POST /sources)도
    이 함수를 재사용해 Channel ID 자동 추출을 시도한다 — 공개 함수로 유지."""
    response = client.get(f"https://www.youtube.com/@{handle}", timeout=15.0)
    response.raise_for_status()
    match = _CHANNEL_ID_RE.search(response.text)
    return match.group(1) if match else ""


def _parse_channel_videos(channel_id: str, client) -> list[dict]:
    response = client.get(f"https://www.youtube.com/channel/{channel_id}/videos", timeout=15.0)
    response.raise_for_status()
    match = _YT_INITIAL_DATA_RE.search(response.text)
    if not match:
        return []
    data = json.loads(match.group(1))
    try:
        tabs = data["contents"]["twoColumnBrowseResultsRenderer"]["tabs"]
        contents = tabs[1]["tabRenderer"]["content"]["richGridRenderer"]["contents"]
    except (KeyError, IndexError):
        return []

    videos = []
    for item in contents:
        rir = item.get("richItemRenderer", {}).get("content", {})
        if "lockupViewModel" in rir:
            lv = rir["lockupViewModel"]
            video_id = lv.get("contentId", "")
            if not video_id:
                continue
            metadata = lv.get("metadata", {}).get("lockupMetadataViewModel", {})
            title = metadata.get("title", {}).get("content", "")
            parts = (metadata.get("metadata", {}).get("contentMetadataViewModel", {})
                     .get("metadataRows", [{}])[0].get("metadataParts", []))
            date_text = parts[1].get("text", {}).get("content", "") if len(parts) > 1 else ""
            videos.append({"video_id": video_id, "title": title, "date_text": date_text})
        elif "videoRenderer" in rir:
            vr = rir["videoRenderer"]
            video_id = vr.get("videoId", "")
            title = "".join(r.get("text", "") for r in vr.get("title", {}).get("runs", []))
            date_text = vr.get("publishedTimeText", {}).get("simpleText", "")
            videos.append({"video_id": video_id, "title": title, "date_text": date_text})
    return videos[:3]


def collect_youtube(source, client, max_age_days: int = 7) -> list[CollectedItem]:
    """채널의 최신 영상(최대 3개, 최근 max_age_days일 이내)을 가져온다."""
    channel_id = source.channel_id or resolve_channel_id(source.handle, client)
    if not channel_id:
        return []
    videos = _parse_channel_videos(channel_id, client)
    items = []
    for video in videos:
        if not video["video_id"]:
            continue
        age = _relative_age_days(video["date_text"])
        if age is not None and age > max_age_days:
            continue
        items.append(_build_item(
            title=video["title"], excerpt="", thumbnail_url=None,
            external_url=f"https://youtu.be/{video['video_id']}",
            published_date=_relative_date_to_iso(video["date_text"]),
            source_name=f"YouTube: {source.name}",
        ))
    return items


# ─────────────────────────── 와쌉 카페 (scrape_wassap 포팅) ───────────────────────────
_TAG_RE = re.compile(r'<[^>]+>')
_WASSAP_LIST_RE = re.compile(
    r'href="/ArticleRead\.nhn\?clubid=\d+&amp;articleid=(\d+)"'
    r'[^>]*title="답(\d+)/댓(\d+)"[^>]*>\s*<div class="ellipsis tcol-c">([^<]+)</div>'
)
_WASSAP_BODY_RE = re.compile(r'sds-comps-text-type-body1[^>]*>(.*?)</span>', re.DOTALL)


def _strip_tags(value: str) -> str:
    return _TAG_RE.sub("", value).strip()


def collect_wassap(source, client, naver_cookie: str, max_items: int = 10) -> list[CollectedItem]:
    """카페 메인 리스트에서 반응수 상위 max_items건 + 검색으로 snippet 보강."""
    cafe_headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": "https://cafe.naver.com",
        "Cookie": naver_cookie,
    }
    list_url = (
        f"https://cafe.naver.com/{source.cafe_id}"
        f"?iframe_url=/ArticleList.nhn%3Fsearch.clubid%3D{source.clubid}%26search.boardtype%3DL"
    )
    response = client.get(list_url, headers=cafe_headers, timeout=15.0)
    response.raise_for_status()
    list_html = response.content.decode("euc-kr", errors="ignore")

    articles: list[dict] = []
    seen: set[str] = set()
    for art_id, reply_count, comment_count, title in _WASSAP_LIST_RE.findall(list_html):
        if art_id in seen:
            continue
        seen.add(art_id)
        title = title.strip()
        if "[공지]" in title:
            continue
        articles.append({
            "id": art_id, "title": title,
            "comments": int(comment_count) + int(reply_count),
            "url": f"https://cafe.naver.com/{source.cafe_id}/{art_id}",
        })

    articles.sort(key=lambda a: (-a["comments"], -int(a["id"])))
    articles = articles[:max_items]

    search_headers = {**cafe_headers, "Referer": "https://www.naver.com"}
    for art in articles:
        snippet_pattern = re.compile(
            rf'href="[^"]*{re.escape(source.cafe_id)}/{art["id"]}[^"]*"[^>]*'
            rf'data-heatmap-target="\.link"[^>]*>(.*?)</a>',
            re.DOTALL,
        )
        art["snippet"] = ""
        for keyword in (f"와쌉 {art['title'][:20]}", art["title"][:15]):
            try:
                search_response = client.get(
                    "https://search.naver.com/search.naver",
                    params={"where": "cafearticle", "query": keyword, "sort": "1"},
                    headers=search_headers, timeout=15.0,
                )
                search_response.raise_for_status()
                html = search_response.text
                link_match = snippet_pattern.search(html)
                if link_match:
                    body_match = _WASSAP_BODY_RE.search(html, link_match.end(), link_match.end() + 1500)
                    if body_match:
                        art["snippet"] = _strip_tags(body_match.group(1))[:120]
                        break
            except Exception:  # noqa: BLE001 — snippet 보강 실패는 무시하고 제목만으로 계속
                continue

    return [
        _build_item(
            title=art["title"], excerpt=art["snippet"], thumbnail_url=None,
            external_url=art["url"], published_date=None, source_name="와쌉",
        )
        for art in articles
    ]
