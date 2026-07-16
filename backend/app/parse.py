from __future__ import annotations
import re
from dataclasses import dataclass
from bs4 import BeautifulSoup

from .brand_match import make_excerpt

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass
class ParsedArticle:
    title: str
    excerpt: str
    thumbnail_url: str | None
    published_date: str | None


def extract_visible_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text(separator=" ")
    return re.sub(r"\s+", " ", text).strip()


# ingest-press.ts의 parsePressPageMeta를 그대로 이식. og:description/og:title이
# 컬럼 길이(title VARCHAR(500), excerpt VARCHAR(500))를 넘거나
# article:published_time이 ISO 8601이 아닌 사이트가 실제로 있었던 문제를 동일하게 방어.
def parse_article_meta(html: str, fallback_title: str) -> ParsedArticle:
    soup = BeautifulSoup(html, "lxml")

    def meta_content(prop: str) -> str | None:
        tag = soup.find("meta", attrs={"property": prop})
        if not tag:
            return None
        content = (tag.get("content") or "").strip()
        return content or None

    og_title = meta_content("og:title")
    title = (og_title or fallback_title).strip()[:500].strip()

    og_description = meta_content("og:description")
    excerpt = make_excerpt(og_description or extract_visible_text(html))

    # thumbnail_path 컬럼이 VARCHAR(500) — title/excerpt와 같은 이유로 CDN
    # 서명 URL이 긴 사이트에서 INSERT가 깨지는 걸 방지하기 위해 동일하게 자른다.
    og_image = meta_content("og:image")
    thumbnail_url = og_image[:500] if og_image else None

    published_raw = meta_content("article:published_time") or meta_content("og:updated_time")
    published_candidate = published_raw[:10] if published_raw else None
    published_date = (
        published_candidate
        if published_candidate and _DATE_RE.match(published_candidate)
        else None
    )

    return ParsedArticle(
        title=title,
        excerpt=excerpt,
        thumbnail_url=thumbnail_url,
        published_date=published_date,
    )
