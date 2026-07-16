from __future__ import annotations
import base64
import re
import time
from typing import Protocol
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


GITHUB_API_BASE = "https://api.github.com"
SOURCES_REPO = "1kmwine/NARA-APP-Wine-Scrapper"
SOURCES_PATH = "docs/scraping-sources.md"
_CACHE_TTL_SECONDS = 30.0

_cache: dict = {"text": None, "sha": None, "fetched_at": 0.0}


class GitHubClient(Protocol):
    def get(self, url: str, *, headers: dict | None = None, timeout: float | None = None): ...
    def put(self, url: str, *, json: dict | None = None, headers: dict | None = None, timeout: float | None = None): ...


def _sources_url() -> str:
    return f"{GITHUB_API_BASE}/repos/{SOURCES_REPO}/contents/{SOURCES_PATH}"


def _auth_headers(github_token: str) -> dict:
    return {"Authorization": f"token {github_token}", "Accept": "application/vnd.github.v3+json"}


def _fetch_sources_document(client: GitHubClient, github_token: str) -> tuple[str, str]:
    response = client.get(_sources_url(), headers=_auth_headers(github_token), timeout=10.0)
    response.raise_for_status()
    body = response.json()
    text = base64.b64decode(body["content"] + "==").decode("utf-8")
    return text, body["sha"]


def load_sources_document(
    client: GitHubClient, github_token: str, *, force_refresh: bool = False
) -> tuple[str, str]:
    """GitHub Contents API로 scraping-sources.md 원문+SHA를 가져온다.

    raw.githubusercontent.com은 CDN 캐시로 수분간 구버전을 반환할 수 있어 Contents API를
    쓴다 (WINE-BRIEFING/scrape.py와 동일한 이유). _CACHE_TTL_SECONDS 동안은 재사용해 job마다
    반복 호출하지 않는다. 소스 추가 직후에는 force_refresh=True로 무효화한다.
    """
    now = time.monotonic()
    if not force_refresh and _cache["text"] is not None and now - _cache["fetched_at"] < _CACHE_TTL_SECONDS:
        return _cache["text"], _cache["sha"]
    text, sha = _fetch_sources_document(client, github_token)
    _cache.update(text=text, sha=sha, fetched_at=now)
    return text, sha


def invalidate_sources_cache() -> None:
    _cache.update(text=None, sha=None, fetched_at=0.0)


def load_sources(client: GitHubClient, github_token: str, *, force_refresh: bool = False) -> SourcesConfig:
    """GitHub에서 로드+파싱까지 한 번에 수행하는 편의 함수."""
    text, _sha = load_sources_document(client, github_token, force_refresh=force_refresh)
    return parse_sources_document(text)


class DuplicateSourceError(Exception):
    pass


class SourcesWriteConflictError(Exception):
    pass


def _insert_table_row_after_section(text: str, section_header_prefix: str, new_row: str) -> str:
    start = text.find(section_header_prefix)
    if start == -1:
        raise ValueError(f"{section_header_prefix} 섹션을 찾을 수 없습니다")
    end = text.find("\n## ", start + len(section_header_prefix))
    section_end = end if end != -1 else len(text)
    section = text[start:section_end]
    lines = section.splitlines(keepends=True)
    last_row_idx = None
    for i, line in enumerate(lines):
        if line.strip().startswith("|"):
            last_row_idx = i
    if last_row_idx is None:
        raise ValueError(f"{section_header_prefix} 섹션에서 표를 찾을 수 없습니다")
    lines.insert(last_row_idx + 1, new_row if new_row.endswith("\n") else new_row + "\n")
    return text[:start] + "".join(lines) + text[section_end:]


def _insert_bullet_after_section(text: str, section_header_prefix: str, new_bullet: str) -> str:
    start = text.find(section_header_prefix)
    if start == -1:
        raise ValueError(f"{section_header_prefix} 섹션을 찾을 수 없습니다")
    end = text.find("\n### ", start + len(section_header_prefix))
    end2 = text.find("\n## ", start + len(section_header_prefix))
    candidates = [e for e in (end, end2) if e != -1]
    section_end = min(candidates) if candidates else len(text)
    section = text[start:section_end]
    lines = section.splitlines(keepends=True)
    last_bullet_idx = None
    for i, line in enumerate(lines):
        if line.strip().startswith("-"):
            last_bullet_idx = i
    if last_bullet_idx is None:
        raise ValueError(f"{section_header_prefix} 섹션에서 항목 목록을 찾을 수 없습니다")
    lines.insert(last_bullet_idx + 1, new_bullet if new_bullet.endswith("\n") else new_bullet + "\n")
    return text[:start] + "".join(lines) + text[section_end:]


def _commit(client: GitHubClient, github_token: str, new_text: str, sha: str, message: str) -> None:
    payload = {
        "message": message,
        "content": base64.b64encode(new_text.encode("utf-8")).decode("ascii"),
        "sha": sha,
    }
    response = client.put(_sources_url(), json=payload, headers=_auth_headers(github_token), timeout=20.0)
    if response.status_code == 409:
        raise SourcesWriteConflictError("다른 프로세스가 먼저 문서를 수정했습니다. 다시 시도해주세요.")
    response.raise_for_status()
    invalidate_sources_cache()


def add_news_source(client: GitHubClient, github_token: str, *, press: str, category: str, query: str, url: str) -> None:
    text, sha = load_sources_document(client, github_token, force_refresh=True)
    domain = _domain_from_url(url)
    existing = parse_sources_document(text)
    if any(s.domain == domain for s in existing.news):
        raise DuplicateSourceError(f"이미 등록된 URL입니다: {url}")
    new_row = f"| {press} | {category} | {query} | {url} |"
    new_text = _insert_table_row_after_section(text, "## 국내 뉴스·매거진", new_row)
    _commit(client, github_token, new_text, sha, f"docs: 뉴스 소스 추가 - {press}")


def add_youtube_source(client: GitHubClient, github_token: str, *, name: str, url: str, channel_id: str = "") -> None:
    text, sha = load_sources_document(client, github_token, force_refresh=True)
    existing = parse_sources_document(text)
    handle_match = re.search(r'youtube\.com/@([\w.-]+)', url)
    handle = handle_match.group(1) if handle_match else ""
    if any(s.handle == handle for s in existing.youtube):
        raise DuplicateSourceError(f"이미 등록된 채널입니다: {url}")
    new_row = f"| {name} | {url} | {channel_id} |"
    new_text = _insert_table_row_after_section(text, "## 유튜브", new_row)
    _commit(client, github_token, new_text, sha, f"docs: 유튜브 소스 추가 - {name}")


def add_wassap_source(client: GitHubClient, github_token: str, *, url: str, clubid: str) -> None:
    text, sha = load_sources_document(client, github_token, force_refresh=True)
    existing = parse_sources_document(text)
    if any(s.clubid == clubid for s in existing.wassap):
        raise DuplicateSourceError(f"이미 등록된 카페입니다: {url}")
    new_bullet = f"- {url} (clubid: {clubid})"
    new_text = _insert_bullet_after_section(text, "### 와쌉", new_bullet)
    _commit(client, github_token, new_text, sha, f"docs: 와쌉 소스 추가 - {url}")


def add_international_source(client: GitHubClient, github_token: str, *, name: str, url: str, note: str = "") -> None:
    text, sha = load_sources_document(client, github_token, force_refresh=True)
    existing = parse_sources_document(text)
    if any(s.name == name for s in existing.international):
        raise DuplicateSourceError(f"이미 등록된 소스입니다: {name}")
    new_row = f"| {name} | ✅ 수집 중 | {url} | {note} |"
    new_text = _insert_table_row_after_section(text, "## 해외·통계·이벤트", new_row)
    _commit(client, github_token, new_text, sha, f"docs: 해외소스 추가 - {name}")
