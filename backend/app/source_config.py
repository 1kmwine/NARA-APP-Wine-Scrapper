from __future__ import annotations
import re
from urllib.parse import urlparse

from .sources import NewsSource, YoutubeSource, WassapSource, InternationalSource, SourcesConfig

_NEWS_ROW_RE = re.compile(
    r'\|\s*([^|]+?)\s*\|\s*(매거진|뉴스)\s*\|\s*([^|]+?)\s*\|\s*(https?://[^\s|]+)\s*\|'
)
_YOUTUBE_ROW_RE = re.compile(
    r'\|\s*([^|]+?)\s*\|\s*https?://www\.youtube\.com/@([\w.-]+)\s*\|\s*(UC[\w-]{22}|[^|]*?)\s*\|'
)
_WASSAP_BULLET_RE = re.compile(r'-\s*(https?://\S+?)\s*\(clubid:\s*(\d+)\)')
_INTERNATIONAL_ROW_RE = re.compile(
    r'\|\s*([^|]+?)\s*\|\s*(✅[^|]*|❌[^|]*)\s*\|\s*(https?://[^\s|]+)\s*\|'
)
_QUERY_BLOCK_RE = re.compile(r'```수집쿼리\s*(.*?)```', re.DOTALL)


def _extract_section(text: str, header_prefix: str) -> str:
    """header_prefix로 시작하는 절을 다음 '\\n## ' 헤더 전까지 잘라 반환. 없으면 빈 문자열."""
    start = text.find(header_prefix)
    if start == -1:
        return ""
    end = text.find("\n## ", start + len(header_prefix))
    return text[start:end] if end != -1 else text[start:]


def _domain_from_url(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def _slugify(name: str) -> str:
    slug = re.sub(r'[^a-z0-9]+', '-', name.strip().lower()).strip('-')
    return slug or name


def _parse_news(text: str) -> list[NewsSource]:
    section = _extract_section(text, "## 국내 뉴스·매거진")
    sources = []
    for press, _category, query, url in _NEWS_ROW_RE.findall(section):
        domain = _domain_from_url(url)
        if not domain:
            continue
        sources.append(NewsSource(id=domain, name=press.strip(), domain=domain, query=query.strip()))
    return sources


def _parse_youtube(text: str) -> list[YoutubeSource]:
    section = _extract_section(text, "## 유튜브")
    sources = []
    for name, handle, channel_id in _YOUTUBE_ROW_RE.findall(section):
        handle = handle.strip()
        channel_id = channel_id.strip()
        sources.append(YoutubeSource(
            id=handle, name=name.strip(), handle=handle,
            channel_id=channel_id if channel_id.startswith("UC") else "",
        ))
    return sources


def _parse_wassap(text: str) -> list[WassapSource]:
    section = _extract_section(text, "### 와쌉")
    sources = []
    for url, clubid in _WASSAP_BULLET_RE.findall(section):
        path = urlparse(url).path.strip("/")
        cafe_id = path.split("/")[0] if path else ""
        if not cafe_id:
            continue
        sources.append(WassapSource(id=f"{cafe_id}-{clubid}", name="와쌉", cafe_id=cafe_id, clubid=clubid))
    return sources


def _parse_international(text: str) -> list[InternationalSource]:
    section = _extract_section(text, "## 해외·통계·이벤트")
    sources = []
    for name, status, url in _INTERNATIONAL_ROW_RE.findall(section):
        if "✅" not in status:
            continue
        name = name.strip()
        sources.append(InternationalSource(id=_slugify(name), name=name, url=url.strip()))
    return sources


def _parse_age_youtube(text: str) -> int:
    block = _QUERY_BLOCK_RE.search(text)
    if not block:
        return 7
    for line in block.group(1).strip().splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            if key.strip() == "최근_유튜브_일수":
                try:
                    return int(value.strip())
                except ValueError:
                    return 7
    return 7


def parse_sources_document(text: str) -> SourcesConfig:
    """scraping-sources.md 원문을 파싱한다 (네트워크 호출 없음, 순수 함수)."""
    return SourcesConfig(
        news=_parse_news(text),
        youtube=_parse_youtube(text),
        wassap=_parse_wassap(text),
        international=_parse_international(text),
        age_youtube=_parse_age_youtube(text),
    )
