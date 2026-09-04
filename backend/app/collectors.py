from __future__ import annotations
import html as html_module
import json
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import NamedTuple

import httpx

from .brand_match import fuzzy_find, make_excerpt
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


def search_wassap(query: str, source, client, naver_cookie: str, max_items: int = 10) -> list[CollectedItem]:
    """카페 자체 리스트/검색(ArticleList.nhn/ArticleSearchList.nhn)은 검색어를
    무시하거나(2026-07-21 실측) 빈 응답을 준다(2026-07-22 실측 — 신형 SPA 카페라
    게시글 상세/검색 모두 클라이언트 XHR). 대신 그 SPA가 실제로 호출하는 내부
    검색 API(apis.cafe.naver.com)를 직접 부른다 — page.js 번들에서 URL 패턴과
    필수 헤더(X-Cafe-Product/Version/Phase, 없으면 400)를 확인해서 알아냄
    (2026-07-23). title/snippet/thumbnail이 API 응답에 다 있어 별도 스니펫
    보강이 필요 없다.

    cafe_numeric_id(신형 카페 전용 숫자 ID, clubid와 무관)가 없으면 이 소스는
    건너뛴다 — WassapSource 문서 참고."""
    if not source.cafe_numeric_id:
        return []

    headers = {
        "Cookie": naver_cookie,
        "Referer": f"https://cafe.naver.com/f-e/cafes/{source.cafe_numeric_id}/menus/0",
        "Origin": "https://cafe.naver.com",
        "Accept": "application/json, text/plain, */*",
        "User-Agent": "Mozilla/5.0",
        "X-Cafe-Product": "pc",
        "X-Cafe-Version": "1.0",
        "X-Cafe-Phase": "real",
    }
    response = client.get(
        f"https://apis.cafe.naver.com/search/v2/cafes/{source.cafe_numeric_id}/search/articles",
        params={"query": query, "perPage": max_items, "page": 1},
        headers=headers, timeout=15.0,
    )
    response.raise_for_status()
    data = response.json()
    entries = data.get("result", {}).get("articleList") or []

    items: list[CollectedItem] = []
    for entry in entries:
        if entry.get("type") != "ARTICLE":
            continue
        it = entry.get("item") or {}
        title = _strip_tags(it.get("subject") or "")
        if not title:
            continue
        article_id = it.get("articleId")
        items.append(_build_item(
            title=title,
            excerpt=_strip_tags(it.get("summary") or "")[:150],
            thumbnail_url=it.get("thumbnailImageUrl") or None,
            external_url=f"https://cafe.naver.com/{source.cafe_id}/{article_id}",
            published_date=(it.get("addDate") or "")[:10] or None,
            source_name="와쌉",
        ))
        if len(items) >= max_items:
            break
    return items


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


def default_translate_to_en(text: str) -> str:
    """한국어 → 영문 (무료 Google Translate 엔드포인트). 해외소스는 전부 영어라
    한글 검색어 그대로 넘기면 아무것도 안 걸린다 — 검색 전에 영문으로 바꾼다.
    실패 시 원문 그대로 반환.

    이미 영문(ASCII)이면 그대로 반환한다 — main.py가 integrated_item_info DB에서
    먼저 정확한 영문 표기를 찾고(find_english_name), 못 찾을 때만 이 함수로
    넘어오는데, DB에서 이미 영문을 찾은 경우 여기서 또 번역기를 태우면 오히려
    표기가 깨질 수 있다(예: 이미 "Caymus"인데 재번역 위험)."""
    if not text:
        return ""
    if text.isascii():
        return text
    try:
        response = httpx.get(
            "https://translate.googleapis.com/translate_a/single",
            params={"client": "gtx", "sl": "ko", "tl": "en", "dt": "t", "q": text},
            timeout=10.0,
        )
        response.raise_for_status()
        data = response.json()
        return "".join(segment[0] for segment in data[0])
    except Exception:  # noqa: BLE001
        return text


def _parse_decanter(client, translate, query: str) -> list[CollectedItem]:
    # Decanter는 검색이 자바스크립트 위젯이라(2026-07-22 실측 — /?s=로 정적
    # 요청해도 검색 결과가 아니라 홈 화면이 그대로 옴) 서버 사이드로 검색을 못 한다.
    # query가 있어도 최신 wine-news만 가져온다 — 검색어 무관 소스 중 유일하게 남음.
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


def _parse_wine_spectator(client, translate, query: str) -> list[CollectedItem]:
    if query:
        # 실제 사이트 검색(/search?q=, 헤더 검색폼의 name="q" — 2026-07-22 확인).
        # 기사(articles)뿐 아니라 와인 평점 DB(site-search__result-title)까지
        # 같이 나오는데, 특정 와인명 검색에선 오히려 이쪽이 더 자주 걸린다.
        response = client.get(
            "https://www.winespectator.com/search", params={"q": query}, timeout=15.0,
        )
        response.raise_for_status()
        matches = re.findall(
            r'<h2 class="site-search__result-title"><a href="([^"]+)">([^<]*)</a></h2>', response.text)
        items = []
        for path, title in matches[:3]:
            title = title.strip()
            if not title or _is_placeholder(title):
                continue
            url = path if path.startswith("http") else f"https://www.winespectator.com{path}"
            items.append(_build_item(
                title=translate(title), excerpt="", thumbnail_url=None,
                external_url=url, published_date=None, source_name="Wine Spectator",
            ))
        if items:
            return items
        # 검색 결과 0건이면 최신 기사로 폴백 — 완전히 빈 카테고리보다 낫다.

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


def _parse_oiv(client, translate, query: str) -> list[CollectedItem]:
    # OIV는 Drupal Views 노출 필터라 rendered_item 파라미터로 실제 서버사이드
    # 검색이 된다(2026-07-22 확인 — "congress"로 필터링하면 그 단어가 들어간
    # 글만 옴, 무필터 결과와 다름).
    if query:
        response = client.get(
            "https://www.oiv.int/news/press", params={"rendered_item": query}, timeout=15.0,
        )
    else:
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


def _parse_drinks_business(client, translate, query: str) -> list[CollectedItem]:
    # thedrinksbusiness.com은 WordPress 실제 서버사이드 검색(?s=)이 된다(2026-07-31
    # 확인 — 무의미한 검색어는 0건, "wine"은 36건으로 실제 필터링됨). 검색결과
    # 카드는 `<a href="URL" class="d-block">...<h2 class="u-fs-h-small mb-3">제목</h2>`.
    # python-httpx 기본 User-Agent는 이 사이트에서 403으로 차단된다(실측 2026-07-31)
    # — 브라우저 UA를 흉내내야 한다.
    headers = {"User-Agent": "Mozilla/5.0"}
    if query:
        response = client.get(
            "https://www.thedrinksbusiness.com/", params={"s": query}, headers=headers, timeout=15.0,
        )
        response.raise_for_status()
        matches = re.findall(
            r'href="(https://www\.thedrinksbusiness\.com/\d{4}/\d{2}/[a-z0-9-]+/)"\s*class="d-block">'
            r'.*?<h2 class="u-fs-h-small mb-3">([^<]+)</h2>',
            response.text, re.DOTALL,
        )
        items = []
        for url, title in matches[:3]:
            title = title.strip()
            if not title or _is_placeholder(title):
                continue
            items.append(_build_item(
                title=translate(title), excerpt="", thumbnail_url=None,
                external_url=url, published_date=None, source_name="The Drinks Business",
            ))
        if items:
            return items
        # 검색 결과 0건이면 최신 기사로 폴백 — 완전히 빈 카테고리보다 낫다.

    response = client.get("https://www.thedrinksbusiness.com/", headers=headers, timeout=15.0)
    response.raise_for_status()
    titles = re.findall(r'<h2 class="c-post-info__heading">([^<]+)</h2>', response.text)
    items = []
    for title in titles[:3]:
        title = title.strip()
        if _is_placeholder(title):
            continue
        items.append(_build_item(
            title=translate(title), excerpt="", thumbnail_url=None,
            external_url="https://www.thedrinksbusiness.com/", published_date=None,
            source_name="The Drinks Business",
        ))
    return items


def _parse_wine_industry_advisor(client, translate, query: str) -> list[CollectedItem]:
    # wineindustryadvisor.com도 WordPress 실서버 검색(?s=)이 된다(2026-07-31 확인
    # — 무의미 검색어는 0건). 검색결과는 `<h3 class="elementor-post__title"><a
    # href="URL">제목</a></h3>`, 홈페이지 최신글은 `<h2 class="is-title
    # post-title..."><a href="URL">제목</a>` — 템플릿이 서로 다르다.
    headers = {"User-Agent": "Mozilla/5.0"}
    if query:
        response = client.get(
            "https://www.wineindustryadvisor.com/", params={"s": query}, headers=headers, timeout=15.0,
        )
        response.raise_for_status()
        matches = re.findall(
            r'<h3 class="elementor-post__title">\s*<a href="([^"]+)"\s*>\s*([^\t\n<]+)', response.text,
        )
        items = []
        for url, title in matches[:3]:
            title = title.strip()
            if not title or _is_placeholder(title):
                continue
            items.append(_build_item(
                title=translate(title), excerpt="", thumbnail_url=None,
                external_url=url, published_date=None, source_name="Wine Industry Advisor",
            ))
        if items:
            return items
        # 검색 결과 0건이면 최신 기사로 폴백 — 완전히 빈 카테고리보다 낫다.

    response = client.get("https://www.wineindustryadvisor.com/", headers=headers, timeout=15.0)
    response.raise_for_status()
    matches = re.findall(r'class="is-title post-title[^"]*"><a href="([^"]+)">([^<]+)</a>', response.text)
    items = []
    for url, title in matches[:3]:
        title = title.strip()
        if _is_placeholder(title):
            continue
        items.append(_build_item(
            title=translate(title), excerpt="", thumbnail_url=None,
            external_url=url, published_date=None, source_name="Wine Industry Advisor",
        ))
    return items


def _parse_1winedude(client, translate, query: str) -> list[CollectedItem]:
    # 1winedude.com(개인 와인 블로그, 업계 인지도 있음)도 WordPress 실서버 검색이
    # 된다(2026-07-31 확인 — 무의미 검색어는 다른 결과, "chardonnay"는 실제 관련
    # 글만 나옴). 검색결과 `<h2 class="...post-title"><a href="URL">제목</a>`
    # 안의 클래스 접미사(--13 등)는 Gutenberg 블록 인스턴스 ID라 매번 랜덤이라
    # post-title만 부분 매칭한다. query 없으면 최신글 목록도 같은 템플릿이라
    # 별도 홈페이지 파싱이 필요 없다.
    headers = {"User-Agent": "Mozilla/5.0"}
    response = client.get(
        "https://1winedude.com/", params={"s": query} if query else None, headers=headers, timeout=15.0,
    )
    response.raise_for_status()
    matches = re.findall(
        r'<h2 class="[^"]*post-title[^"]*">\s*<a href="([^"]+)"[^>]*>([^<]+)</a>', response.text,
    )
    items = []
    for url, title in matches[:3]:
        title = title.strip()
        if not title or _is_placeholder(title):
            continue
        items.append(_build_item(
            title=translate(title), excerpt="", thumbnail_url=None,
            external_url=url, published_date=None, source_name="1WineDude",
        ))
    return items


_INTERNATIONAL_PARSERS = {
    "Decanter": _parse_decanter,
    "Wine Spectator": _parse_wine_spectator,
    "OIV": _parse_oiv,
    "The Drinks Business": _parse_drinks_business,
    "Wine Industry Advisor": _parse_wine_industry_advisor,
    "1WineDude": _parse_1winedude,
}


def collect_international(
    source, client, translate=default_translate_to_ko, query: str = "",
    translate_query=default_translate_to_en,
) -> list[CollectedItem]:
    """소스명으로 전용 파서를 찾아 실행한다. Decanter/Wine Spectator/OIV만 지원 —
    scraping-sources.md에 새 해외소스가 ✅로 추가돼도 여기 전용 파서가 없으면
    NotImplementedError로 실패 처리된다 (사이트마다 HTML 구조가 달라 범용 파서를
    만들지 않음 — 새 사이트 추가 시 이 함수에 파서를 직접 구현해야 한다).

    query(한글 검색어)는 영문으로 번역해서 넘긴다 — 해외소스에 한글 그대로
    검색해봐야 걸리는 게 없다. Decanter는 검색 자체가 안 돼 이 값을 무시한다."""
    parser = _INTERNATIONAL_PARSERS.get(source.name)
    if parser is None:
        raise NotImplementedError(f"지원되지 않는 해외소스: {source.name}")
    english_query = translate_query(query) if query else ""
    return parser(client, translate, english_query)


# ─────────────────────────── 해외소스 — 웹 전체 검색 ───────────────────────────
_DDG_RESULT_RE = re.compile(
    r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?class="result__snippet"[^>]*>(.*?)</a>',
    re.DOTALL,
)


def _ddg_target_url(href: str) -> str:
    """DuckDuckGo HTML 결과 링크(//duckduckgo.com/l/?uddg=<실제URL>&rut=...)에서
    실제 목적지 URL을 꺼낸다."""
    from urllib.parse import parse_qs, urlparse
    full = href if href.startswith("http") else f"https:{href}"
    return (parse_qs(urlparse(full).query).get("uddg") or [""])[0]


def _domain_of(url: str) -> str:
    from urllib.parse import urlparse
    host = urlparse(url).netloc
    return host[4:] if host.startswith("www.") else host


# "해외소스" 카테고리 전용 검색이라 국내 사이트가 섞이면 안 된다. DuckDuckGo 전체
# 웹검색은 도메인 제한이 없어서 검색어와 겹치는 국내 블로그·자사 홈페이지도 그냥
# 걸려온다(실측 2026-07-31 — "Alvaro Palacios" 검색에 blog.naver.com, 나라셀라
# 자사 홈페이지 naracellar.com이 "해외소스"로 노출됨). 완벽한 언어 판별 대신
# 알려진 국내 도메인만 걷어낸다 — ponytail: 휴리스틱 차단목록, 새 국내 사이트가
# 계속 걸리면 도메인 추가.
_DOMESTIC_DOMAIN_MARKERS = (".kr", "naver.com", "naracellar.com", "tistory.com", "daum.net")


def _is_domestic_domain(domain: str) -> bool:
    domain = domain.lower()
    return any(domain == marker.lstrip(".") or domain.endswith(marker) for marker in _DOMESTIC_DOMAIN_MARKERS)


def search_web(query: str, client, translate=default_translate_to_ko, max_items: int = 5) -> list[CollectedItem]:
    """Decanter/Wine Spectator/OIV 3곳으로는 커버리지가 너무 좁다(2026-07-22 실측
    — "로저구라트"류 브랜드는 3곳 다 0건). scraping-sources.md에 등록된 소스에
    국한하지 않고 DuckDuckGo HTML 검색(로그인/API 키 불필요)으로 와인 관련 웹
    전체를 훑는다."""
    response = client.get(
        "https://html.duckduckgo.com/html/",
        params={"q": f"{query} wine"},
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=15.0,
    )
    response.raise_for_status()
    html = response.text

    items: list[CollectedItem] = []
    for match in _DDG_RESULT_RE.finditer(html):
        href, raw_title, raw_snippet = match.groups()
        target = _ddg_target_url(href)
        title = _strip_tags(raw_title)
        if not target or not title or _is_placeholder(title):
            continue
        domain = _domain_of(target)
        if _is_domestic_domain(domain):
            continue
        items.append(_build_item(
            title=translate(title), excerpt=translate(_strip_tags(raw_snippet)),
            thumbnail_url=None, external_url=target, published_date=None,
            source_name=domain,
        ))
        if len(items) >= max_items:
            break
    return items


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


# ─────────────────────────── 블로그/와쌉 본문 전체 가져오기 ───────────────────────────
_IMG_SRC_RE = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE)
# 본문 사진이 아닌 것들 — 작성자 프로필(blogpfthumb), 외부 링크 카드 썸네일(dthumb),
# 정적 아이콘, 애니메이션 스티커(.gif). 2026-09-03 실측 기준.
_NON_CONTENT_IMG_RE = re.compile(
    r'blogpfthumb-phinf|dthumb-phinf|ssl\.pstatic\.net/static|\.gif(?:\?|$)',
    re.IGNORECASE,
)


def extract_image_urls(html_str: str, limit: int = 3) -> list[str]:
    """본문 HTML에서 사진 URL을 순서대로 뽑는다. _html_to_lines()는 태그를 벗기면서
    <img>까지 버리므로, 이미지 가격 추출용으로 벗기기 전에 따로 뽑아둔다.

    limit을 두는 이유: 사진 30장짜리 후기 글이 흔한데, 이미지 1장당 추출기 호출이
    한 번씩 붙으므로 호출 수·소요 시간 상한을 보장해야 한다. 5장이었는데 3장으로
    줄였다(2026-09-04) — 시간은 image_price의 글당 예산이 잡아주지만, Gemini 무료
    티어 429가 잦아서 호출 수 자체를 아껴야 한다."""
    urls: list[str] = []
    for match in _IMG_SRC_RE.finditer(html_str):
        url = html_module.unescape(match.group(1)).strip()
        if not url or _NON_CONTENT_IMG_RE.search(url):
            continue
        urls.append(url)
        if len(urls) >= limit:
            break
    return urls


class FetchedBody(NamedTuple):
    """본문 텍스트와 그 글에 붙은 사진 URL을 같이 나른다 — 이미지 가격 추출이
    본문을 다시 내려받지 않아도 되게(한 번 받은 HTML에서 둘 다 뽑는다)."""
    text: str
    image_urls: list[str]


_SCRIPT_STYLE_RE = re.compile(r'<(script|style)\b[^>]*>.*?</\1>', re.DOTALL | re.IGNORECASE)
_BLOCK_BREAK_RE = re.compile(r'</p>|<br\s*/?>|</div>', re.IGNORECASE)
_TAG_RE = re.compile(r'<[^>]+>')


def _html_to_lines(html_str: str) -> str:
    """블록 태그(</p>, <br>, </div>)를 줄바꿈으로 바꾼 뒤 나머지 태그를 벗기고
    HTML 엔티티(&#x3D; 등, Smart Editor 콘텐츠에 흔함)를 복원한다. 빈 줄은 버린다.
    <script>/<style> 블록은 태그+내용째 통째로 먼저 제거한다 — 안 그러면 JS/CSS
    텍스트가 그대로 새서 가격 추출 단계에서 오탐(채널명+가격 패턴이 우연히 코드
    안에 같이 있는 경우)이 생길 수 있다."""
    text = _SCRIPT_STYLE_RE.sub('', html_str)
    text = _BLOCK_BREAK_RE.sub('\n', text)
    text = _TAG_RE.sub('', text)
    text = html_module.unescape(text)
    lines = [ln.strip() for ln in text.split('\n')]
    return '\n'.join(ln for ln in lines if ln)


def fetch_blog_full_body(external_url: str, client) -> FetchedBody | None:
    """검색 스니펫(description)만으론 본문 속 가격 언급을 못 잡는다. m.blog.naver.com은
    PC용 PostView.naver(iframe 껍데기, og:image만 있음)와 달리 본문을 서버에서
    직접 렌더링해준다."""
    match = _BLOG_LINK_RE.search(external_url)
    if not match:
        return None
    blog_id, log_no = match.groups()
    try:
        response = client.get(f"https://m.blog.naver.com/{blog_id}/{log_no}", timeout=10.0)
        response.raise_for_status()
        return FetchedBody(text=_html_to_lines(response.text), image_urls=extract_image_urls(response.text))
    except Exception:  # noqa: BLE001 — 이 게시글만 스킵, 전체 검색은 계속
        return None


_ARTICLE_ID_RE = re.compile(r'cafe\.naver\.com/[\w-]+/(\d+)')


def fetch_wassap_full_body(cafe_numeric_id: str, external_url: str, client, naver_cookie: str) -> FetchedBody | None:
    """search_wassap()의 summary(150자 스니펫)만으론 본문 속 가격 언급을 못 잡는다.
    게시글 상세 API(2026-08-31 devtools로 실측 확인)로 본문 전체(contentHtml)를
    가져온다. CU픽업주문 위젯/이미지 안의 가격은 이 방식으로도 못 잡음(정규식
    범위 밖, se-text 문단 텍스트만 대상)."""
    match = _ARTICLE_ID_RE.search(external_url)
    if not match:
        return None
    article_id = match.group(1)
    headers = {
        "Cookie": naver_cookie,
        "Referer": external_url,
        "Origin": "https://cafe.naver.com",
        "Accept": "application/json, text/plain, */*",
        "User-Agent": "Mozilla/5.0",
        "X-Cafe-Product": "pc",
        "X-Cafe-Version": "1.0",
        "X-Cafe-Phase": "real",
    }
    try:
        response = client.get(
            f"https://article.cafe.naver.com/gw/v4/cafes/{cafe_numeric_id}/articles/{article_id}",
            params={"query": "", "fromPopular": "true", "useCafeId": "true", "requestFrom": "A"},
            headers=headers, timeout=15.0,
        )
        response.raise_for_status()
        content_html = response.json().get("result", {}).get("article", {}).get("contentHtml") or ""
        text = _html_to_lines(content_html)
        if not text:
            return None
        return FetchedBody(text=text, image_urls=extract_image_urls(content_html))
    except Exception:  # noqa: BLE001 — 이 게시글만 스킵, 전체 검색은 계속
        return None
