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
