from __future__ import annotations
import json
import re
from dataclasses import dataclass
from datetime import date, timedelta

import httpx

from .brand_match import make_excerpt
from .naver_search import search_blog


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
            sources_ = (lv.get("contentImage", {}).get("thumbnailViewModel", {})
                        .get("image", {}).get("sources", []))
            thumbnail_url = sources_[-1]["url"] if sources_ else None
            videos.append({"video_id": video_id, "title": title, "date_text": date_text, "thumbnail_url": thumbnail_url})
        elif "videoRenderer" in rir:
            vr = rir["videoRenderer"]
            video_id = vr.get("videoId", "")
            title = "".join(r.get("text", "") for r in vr.get("title", {}).get("runs", []))
            date_text = vr.get("publishedTimeText", {}).get("simpleText", "")
            thumbs = vr.get("thumbnail", {}).get("thumbnails", [])
            thumbnail_url = thumbs[-1]["url"] if thumbs else None
            videos.append({"video_id": video_id, "title": title, "date_text": date_text, "thumbnail_url": thumbnail_url})
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
            title=video["title"], excerpt="", thumbnail_url=video["thumbnail_url"],
            external_url=f"https://youtu.be/{video['video_id']}",
            published_date=_relative_date_to_iso(video["date_text"]),
            source_name=f"YouTube: {source.name}",
        ))
    return items


# ─────────────────────────── 유튜브 검색(등록 채널 무관) ───────────────────────────
def _parse_search_videos(html_text: str) -> list[dict]:
    match = _YT_INITIAL_DATA_RE.search(html_text)
    if not match:
        return []
    data = json.loads(match.group(1))
    try:
        sections = (data["contents"]["twoColumnSearchResultsRenderer"]["primaryContents"]
                    ["sectionListRenderer"]["contents"])
    except (KeyError, IndexError):
        return []

    videos = []
    for section in sections:
        for item in section.get("itemSectionRenderer", {}).get("contents", []):
            vr = item.get("videoRenderer")
            if not vr:
                continue
            video_id = vr.get("videoId", "")
            if not video_id:
                continue
            title = "".join(r.get("text", "") for r in vr.get("title", {}).get("runs", []))
            date_text = vr.get("publishedTimeText", {}).get("simpleText", "")
            channel = "".join(r.get("text", "") for r in vr.get("longBylineText", {}).get("runs", []))
            thumbs = vr.get("thumbnail", {}).get("thumbnails", [])
            thumbnail_url = thumbs[-1]["url"] if thumbs else None
            videos.append({
                "video_id": video_id, "title": title, "date_text": date_text,
                "channel": channel, "thumbnail_url": thumbnail_url,
            })
    return videos


def collect_youtube_search(query: str, client, max_items: int = 12) -> list[CollectedItem]:
    """등록 채널의 최신 영상만으로는 커버리지가 너무 좁다 — 대부분의 검색어에서
    0건이 나온다(채널 11개가 마침 그 브랜드를 다룬 최근 영상이 있어야만 걸림).
    유튜브 공식 Data API 키가 없으므로, 채널 페이지와 같은 방식으로 검색결과
    페이지 자체의 ytInitialData를 파싱한다."""
    response = client.get(
        "https://www.youtube.com/results",
        params={"search_query": query}, timeout=15.0,
        headers={"Accept-Language": "ko-KR,ko;q=0.9"},
    )
    response.raise_for_status()
    videos = _parse_search_videos(response.text)[:max_items]
    return [
        _build_item(
            title=v["title"], excerpt="", thumbnail_url=v["thumbnail_url"],
            external_url=f"https://youtu.be/{v['video_id']}",
            published_date=_relative_date_to_iso(v["date_text"]),
            source_name=f"YouTube: {v['channel']}" if v["channel"] else "YouTube 검색",
        )
        for v in videos
    ]


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
    """카페 메인 리스트에서 최신 max_items건 + 검색으로 snippet 보강한다.

    ArticleList.nhn에 search.query/search.page를 붙여 카페 내부 검색·페이지네이션을
    시도해봤으나(2026-07-21 실측) 둘 다 무시되고 항상 같은 최신 10건이 돌아왔다 —
    이 카페 스킨은 이 방식으론 그 이상 못 가져온다(진짜 검색은 카페 API 권한이
    필요, 범위 밖). 그래서 반응수 상위가 아니라 최신순으로만 정렬해 jobs.py의
    관련성 필터(_matches_query/match_brands)에 넘긴다 — 인기글에 밀려 최신 관련
    글이 빠지는 일은 없지만, 애초에 카페 쪽에서 가져오는 절대량 자체는 늘릴 수
    없다."""
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

    articles.sort(key=lambda a: -int(a["id"]))
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


# ─────────────────────────── 해외소스 (scrape_international 포팅) ───────────────────────────
_PLACEHOLDER_RE = re.compile(r'[A-Z0-9_]+')


def _is_placeholder(text: str) -> bool:
    return bool(_PLACEHOLDER_RE.fullmatch(text.strip()))


def default_translate_to_ko(text: str) -> str:
    """영문 → 한국어 (무료 Google Translate 엔드포인트). 실패 시 원문 그대로 반환 — 지어내지 않는다."""
    if not text:
        return ""
    try:
        response = httpx.get(
            "https://translate.googleapis.com/translate_a/single",
            params={"client": "gtx", "sl": "en", "tl": "ko", "dt": "t", "q": text},
            timeout=10.0,
        )
        response.raise_for_status()
        data = response.json()
        return "".join(segment[0] for segment in data[0])
    except Exception:  # noqa: BLE001 — 번역 실패는 원문 유지로 방어
        return text


def _parse_decanter(client, translate) -> list[CollectedItem]:
    response = client.get("https://www.decanter.com/wine-news/", timeout=15.0)
    response.raise_for_status()
    html = response.text
    titles = re.findall(r'class="listing__title">\s*([^<]{8,150}?)\s*<', html)
    synopses = re.findall(r'class="listing__text listing__text--synopsis">\s*([^<]{10,200}?)\s*<', html)
    items = []
    for title, synopsis in list(zip(titles, synopses))[:3]:
        title, synopsis = title.strip(), synopsis.strip()
        if _is_placeholder(title):
            continue
        items.append(_build_item(
            title=translate(title), excerpt=translate(synopsis), thumbnail_url=None,
            external_url="https://www.decanter.com/wine-news/", published_date=None, source_name="Decanter",
        ))
    return items


def _parse_wine_spectator(client, translate) -> list[CollectedItem]:
    response = client.get("https://www.winespectator.com/", timeout=15.0)
    response.raise_for_status()
    html = response.text
    matches = re.findall(
        r'href="(https://www\.winespectator\.com/articles/[a-z0-9-]+)"[^>]*>\s*([^<]{10,150})\s*<', html)
    by_url: dict[str, list[str]] = {}
    for url, text in matches:
        by_url.setdefault(url, []).append(text.strip())
    items = []
    for url, texts in list(by_url.items())[:3]:
        title = texts[0]
        summary = texts[1] if len(texts) > 1 else ""
        if _is_placeholder(title):
            continue
        items.append(_build_item(
            title=translate(title), excerpt=translate(summary), thumbnail_url=None,
            external_url=url, published_date=None, source_name="Wine Spectator",
        ))
    return items


def _parse_oiv(client, translate) -> list[CollectedItem]:
    response = client.get("https://www.oiv.int/news/press", timeout=15.0)
    response.raise_for_status()
    html = response.text
    items_found = re.findall(r'href="(/press/[a-z0-9-]+)"[^>]*>\s*([^<]{10,150})\s*<', html)
    items = []
    for path, title in items_found[:3]:
        items.append(_build_item(
            title=translate(title.strip()), excerpt="", thumbnail_url=None,
            external_url="https://www.oiv.int" + path, published_date=None, source_name="OIV",
        ))
    return items


_INTERNATIONAL_PARSERS = {
    "Decanter": _parse_decanter,
    "Wine Spectator": _parse_wine_spectator,
    "OIV": _parse_oiv,
}


def collect_international(source, client, translate=default_translate_to_ko) -> list[CollectedItem]:
    """소스명으로 전용 파서를 찾아 실행한다. Decanter/Wine Spectator/OIV만 지원 —
    scraping-sources.md에 새 해외소스가 ✅로 추가돼도 여기 전용 파서가 없으면
    NotImplementedError로 실패 처리된다 (사이트마다 HTML 구조가 달라 범용 파서를
    만들지 않음 — 새 사이트 추가 시 이 함수에 파서를 직접 구현해야 한다)."""
    parser = _INTERNATIONAL_PARSERS.get(source.name)
    if parser is None:
        raise NotImplementedError(f"지원되지 않는 해외소스: {source.name}")
    return parser(client, translate)


# ─────────────────────────── 네이버 블로그 검색 ───────────────────────────
def _blog_postdate_to_iso(postdate: str) -> str | None:
    if len(postdate) != 8 or not postdate.isdigit():
        return None
    return f"{postdate[:4]}-{postdate[4:6]}-{postdate[6:]}"


_BLOG_LINK_RE = re.compile(r'blog\.naver\.com/([\w-]+)/(\d+)')
_OG_IMAGE_RE = re.compile(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"')


def _fetch_blog_thumbnail(link: str, client) -> str | None:
    """블로그 검색 API 응답엔 썸네일이 없다 — blog.naver.com/{id}/{글번호}는 프레임셋
    껍데기라 og:image가 없고, 실제 내용은 iframe(PostView.naver)에 있다. 썸네일 하나
    보여주자고 전체 글 렌더링에 실패해서 카드 자체가 안 뜨면 안 되니, 실패 시
    조용히 None(이니셜 폴백)으로 넘어간다."""
    match = _BLOG_LINK_RE.search(link)
    if not match:
        return None
    blog_id, log_no = match.groups()
    try:
        response = client.get(
            "https://blog.naver.com/PostView.naver",
            params={
                "blogId": blog_id, "logNo": log_no, "redirect": "Dlog",
                "widgetTypeCall": "true", "noTrackingCode": "true", "directAccess": "false",
            },
            timeout=10.0,
        )
        response.raise_for_status()
        match = _OG_IMAGE_RE.search(response.text)
        return match.group(1) if match else None
    except Exception:  # noqa: BLE001 — 썸네일 실패는 이 아이템만 폴백 처리
        return None


def collect_naver_blog(
    query: str, client_id: str, client_secret: str, client, max_items: int = 15,
) -> list[CollectedItem]:
    """블로그는 뉴스처럼 도메인별 등록 소스 목록이 없다 — 블로거가 수천 명이라 그런
    큐레이션 자체가 안 맞는다. 검색 API가 이미 title/description/postdate까지 주므로
    og:meta 재수집 없이 바로 CollectedItem으로 만든다. API가 sort=date로 이미
    최신순 정렬해 주지만, 너무 많이 잡히면 max_items로 한 번 더 자른다.
    썸네일만 별도로 글 본문 페이지에서 가져온다(API 응답엔 없어서)."""
    items = search_blog(query, client_id, client_secret, client)[:max_items]
    return [
        _build_item(
            title=item["title"], excerpt=item["description"],
            thumbnail_url=_fetch_blog_thumbnail(item["link"], client),
            external_url=item["link"], published_date=_blog_postdate_to_iso(item["postdate"]),
            source_name=f"블로그: {item['bloggername']}" if item["bloggername"] else "네이버 블로그",
        )
        for item in items
    ]
