from __future__ import annotations
import re
import time
from typing import Protocol
from urllib.parse import urlparse

NAVER_NEWS_URL = "https://openapi.naver.com/v1/search/news.json"
NAVER_BLOG_URL = "https://openapi.naver.com/v1/search/blog.json"

_TAG_RE = re.compile(r"<[^>]+>")
_MAX_RETRIES = 2
_DEFAULT_RETRY_DELAY_SECONDS = 0.5
_DEFAULT_CALL_INTERVAL_SECONDS = 0.3


class HttpClient(Protocol):
    def get(self, url: str, *, params=None, headers=None, timeout=None): ...


def _strip_tags(value: str) -> str:
    return _TAG_RE.sub("", value)


def _url_host_matches_domain(url: str, domain: str) -> bool:
    host = urlparse(url).netloc.lower()
    domain = domain.lower()
    return host == domain or host == f"www.{domain}" or host.endswith(f".{domain}")


def naver_search(
    query: str,
    api_url: str,
    client_id: str,
    client_secret: str,
    client: HttpClient,
    display: int = 30,
    retry_delay_seconds: float = _DEFAULT_RETRY_DELAY_SECONDS,
) -> list[dict]:
    """네이버 뉴스/블로그 검색 API 호출. 429 응답 시 최대 2회, 지수 백오프로 재시도한다."""
    headers = {
        "X-Naver-Client-Id": client_id,
        "X-Naver-Client-Secret": client_secret,
    }
    params = {"query": query, "display": display, "sort": "date"}

    response = None
    for attempt in range(_MAX_RETRIES + 1):
        response = client.get(api_url, params=params, headers=headers, timeout=10.0)
        if getattr(response, "status_code", 200) == 429 and attempt < _MAX_RETRIES:
            if retry_delay_seconds:
                time.sleep(retry_delay_seconds * (2 ** attempt))
            continue
        break

    response.raise_for_status()
    items = response.json().get("items", [])
    return [
        {
            "title": _strip_tags(item.get("title", "")),
            "link": item.get("link", ""),
            # 네이버와 제휴된 언론사(예: 한국경제)는 link가 n.news.naver.com으로
            # 재작성되고, 원본 도메인은 originallink에만 남는다.
            "originallink": item.get("originallink", ""),
        }
        for item in items
    ]


def fetch_all_items(
    query: str,
    client_id: str,
    client_secret: str,
    client: HttpClient,
    call_interval_seconds: float = _DEFAULT_CALL_INTERVAL_SECONDS,
) -> list[dict]:
    """뉴스+블로그를 각각 정확히 한 번씩만 호출해 결합된 원본 아이템 리스트를 반환한다.

    소스가 몇 개든 이 함수는 job당 딱 한 번만 호출된다 — 도메인별 필터링은
    items_for_domain()이 네트워크 호출 없이 이 결과에서 나눠 처리한다
    (기존엔 소스 수 × 2회 호출해 네이버 레이트리밋에 걸렸었음).
    """
    items: list[dict] = []
    for i, api_url in enumerate((NAVER_NEWS_URL, NAVER_BLOG_URL)):
        items.extend(naver_search(query, api_url, client_id, client_secret, client))
        if i == 0 and call_interval_seconds:
            time.sleep(call_interval_seconds)
    return items


def items_for_domain(items: list[dict], domain: str) -> list[str]:
    """이미 가져온 아이템 리스트에서 도메인이 일치하는 URL만 뽑는다 (네트워크 호출 없음)."""
    urls: list[str] = []
    for item in items:
        if _url_host_matches_domain(item.get("originallink", ""), domain):
            urls.append(item["originallink"])
        elif _url_host_matches_domain(item.get("link", ""), domain):
            urls.append(item["link"])

    seen: set[str] = set()
    result: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            result.append(u)
    return result
