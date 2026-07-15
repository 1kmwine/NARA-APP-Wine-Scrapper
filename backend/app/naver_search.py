from __future__ import annotations
import re
from typing import Protocol
from urllib.parse import urlparse

NAVER_NEWS_URL = "https://openapi.naver.com/v1/search/news.json"
NAVER_BLOG_URL = "https://openapi.naver.com/v1/search/blog.json"

_TAG_RE = re.compile(r"<[^>]+>")


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
) -> list[dict]:
    headers = {
        "X-Naver-Client-Id": client_id,
        "X-Naver-Client-Secret": client_secret,
    }
    response = client.get(
        api_url,
        params={"query": query, "display": display, "sort": "date"},
        headers=headers,
        timeout=10.0,
    )
    response.raise_for_status()
    items = response.json().get("items", [])
    return [
        {"title": _strip_tags(item.get("title", "")), "link": item.get("link", "")}
        for item in items
    ]


def search_urls_for_domain(
    query: str,
    domain: str,
    client_id: str,
    client_secret: str,
    client: HttpClient,
) -> list[str]:
    urls: list[str] = []
    for api_url in (NAVER_NEWS_URL, NAVER_BLOG_URL):
        items = naver_search(query, api_url, client_id, client_secret, client)
        urls.extend(item["link"] for item in items if _url_host_matches_domain(item["link"], domain))

    seen: set[str] = set()
    result: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            result.append(u)
    return result
