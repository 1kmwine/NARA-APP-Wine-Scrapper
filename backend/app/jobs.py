from __future__ import annotations
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Optional

from .sources import SourcesConfig
from .collectors import CollectedItem
from .naver_search import items_for_domain

logger = logging.getLogger(__name__)


@dataclass
class JobResultItem:
    source_id: str
    source_name: str
    source_category: str
    title: str
    published_date: Optional[str]
    external_url: str
    status: str  # '저장됨' | '중복' | '실패'
    matched_brands: list[str] = field(default_factory=list)
    excerpt: str = ""
    thumbnail_url: Optional[str] = None
    reason: Optional[str] = None


@dataclass
class Job:
    id: str
    wine_name: str
    brand: str
    status: str = "pending"  # pending | running | succeeded | partial | failed
    total: int = 0
    done: int = 0
    results: list[JobResultItem] = field(default_factory=list)
    error: Optional[str] = None


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self, wine_name: str, brand: str, total: int) -> Job:
        job = Job(id=str(uuid.uuid4()), wine_name=wine_name, brand=brand, total=total)
        with self._lock:
            self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def update(self, job_id: str, **changes) -> None:
        with self._lock:
            job = self._jobs[job_id]
            for key, value in changes.items():
                if key not in job.__dataclass_fields__:
                    raise AttributeError(f"Job has no field {key!r}")
                setattr(job, key, value)

    def append_result(self, job_id: str, item: JobResultItem) -> None:
        with self._lock:
            self._jobs[job_id].results.append(item)

    def increment_done(self, job_id: str) -> None:
        with self._lock:
            self._jobs[job_id].done += 1


def _process_collected_item(
    job_id: str, store: JobStore, source_id: str, source_category: str,
    item: CollectedItem, known_brands: list[str],
    article_exists: Callable[[str], bool], insert_article: Callable[..., int],
    match_brands: Callable[[str, list[str]], list[str]],
) -> None:
    """유튜브/와쌉/해외소스처럼 collectors.py가 이미 title/excerpt까지 만들어 반환한
    아이템 하나를 중복확인→매칭→저장까지 처리한다 (og:meta 파싱 불필요)."""
    if article_exists(item.external_url):
        store.append_result(job_id, JobResultItem(
            source_id=source_id, source_name=item.source_name, source_category=source_category,
            title=item.title, published_date=item.published_date, external_url=item.external_url,
            excerpt=item.excerpt, thumbnail_url=item.thumbnail_url, status="중복",
        ))
        return

    matched = match_brands(f"{item.title} {item.excerpt}", known_brands)
    insert_article(item.source_name, item.external_url, item, matched)
    store.append_result(job_id, JobResultItem(
        source_id=source_id, source_name=item.source_name, source_category=source_category,
        title=item.title, published_date=item.published_date, external_url=item.external_url,
        excerpt=item.excerpt, thumbnail_url=item.thumbnail_url, status="저장됨", matched_brands=matched,
    ))


def run_job(
    job_id: str,
    store: JobStore,
    sources: SourcesConfig,
    wine_name: str,
    brand: str,
    fetch_naver_items: Callable[[str], list[dict]],
    fetch_html: Callable[[str], str],
    get_known_brands: Callable[[], list[str]],
    article_exists: Callable[[str], bool],
    insert_article: Callable[..., int],
    parse_article_meta: Callable[[str, str], object],
    match_brands: Callable[[str, list[str]], list[str]],
    extract_visible_text: Callable[[str], str],
    fetch_youtube_items: Callable[[object], list[CollectedItem]],
    fetch_wassap_items: Callable[[object], list[CollectedItem]],
    fetch_international_items: Callable[[object], list[CollectedItem]],
    deadline: float | None = None,
) -> None:
    store.update(job_id, status="running")
    query = brand or wine_name

    try:
        known_brands = get_known_brands()
    except Exception as exc:  # noqa: BLE001 — 소스별 실패와 달리 브랜드 목록 없이는 진행 불가
        store.update(job_id, status="failed", error=f"브랜드 목록 조회 실패: {exc}")
        return

    had_failure = False
    timed_out = False

    def deadline_passed() -> bool:
        return deadline is not None and time.monotonic() > deadline

    # ── 뉴스·매거진: naver 검색을 1회만 호출하고 소스별로는 도메인 필터링만 한다 ──
    if not timed_out and sources.news:
        if deadline_passed():
            timed_out = True
        else:
            try:
                naver_items = fetch_naver_items(query)
                naver_error = None
            except Exception as exc:  # noqa: BLE001
                naver_items = []
                naver_error = str(exc)

            for source in sources.news:
                if deadline_passed():
                    timed_out = True
                    break

                if naver_error is not None:
                    logger.exception("뉴스 검색 실패")
                    had_failure = True
                    store.append_result(job_id, JobResultItem(
                        source_id=source.id, source_name=source.name, source_category="news",
                        title="", published_date=None, external_url="", status="실패",
                        reason=f"뉴스 검색 실패: {naver_error}",
                    ))
                    store.increment_done(job_id)
                    continue

                urls = items_for_domain(naver_items, source.domain)
                for url in urls:
                    if deadline_passed():
                        timed_out = True
                        break
                    try:
                        if article_exists(url):
                            store.append_result(job_id, JobResultItem(
                                source_id=source.id, source_name=source.name, source_category="news",
                                title=url, published_date=None, external_url=url, status="중복",
                            ))
                            continue

                        html = fetch_html(url)
                        article = parse_article_meta(html, wine_name)
                        if not article.title:
                            raise ValueError("파싱된 제목이 비어있음")

                        full_text = f"{article.title} {extract_visible_text(html)}"
                        matched = match_brands(full_text, known_brands)
                        insert_article(source.name, url, article, matched)

                        store.append_result(job_id, JobResultItem(
                            source_id=source.id, source_name=source.name, source_category="news",
                            title=article.title, published_date=article.published_date, external_url=url,
                            excerpt=article.excerpt, thumbnail_url=article.thumbnail_url,
                            status="저장됨", matched_brands=matched,
                        ))
                    except Exception as exc:  # noqa: BLE001 — 이 URL만 실패 처리하고 계속 진행
                        logger.exception("%s 처리 실패", url)
                        had_failure = True
                        store.append_result(job_id, JobResultItem(
                            source_id=source.id, source_name=source.name, source_category="news",
                            title="", published_date=None, external_url=url, status="실패",
                            reason=f"{url} 처리 실패: {exc}",
                        ))

                store.increment_done(job_id)
                if timed_out:
                    break

    # ── 유튜브/와쌉/해외소스: collector가 이미 완성된 아이템을 돌려준다 ──
    category_sources = [
        ("youtube", sources.youtube, fetch_youtube_items),
        ("wassap", sources.wassap, fetch_wassap_items),
        ("international", sources.international, fetch_international_items),
    ]
    for category, source_list, fetch_items in category_sources:
        if timed_out:
            break
        for source in source_list:
            if deadline_passed():
                timed_out = True
                break
            try:
                items = fetch_items(source)
            except Exception as exc:  # noqa: BLE001
                logger.exception("%s(%s) 수집 실패", category, source.name)
                had_failure = True
                store.append_result(job_id, JobResultItem(
                    source_id=source.id, source_name=source.name, source_category=category,
                    title="", published_date=None, external_url="", status="실패",
                    reason=f"{source.name} 수집 실패: {exc}",
                ))
                store.increment_done(job_id)
                continue

            for item in items:
                try:
                    _process_collected_item(
                        job_id, store, source.id, category, item, known_brands,
                        article_exists, insert_article, match_brands,
                    )
                except Exception as exc:  # noqa: BLE001 — 이 아이템만 실패 처리하고 계속 진행
                    logger.exception("%s 저장 실패", item.external_url)
                    had_failure = True
                    store.append_result(job_id, JobResultItem(
                        source_id=source.id, source_name=item.source_name, source_category=category,
                        title="", published_date=None, external_url=item.external_url, status="실패",
                        reason=f"저장 실패: {exc}",
                    ))
            store.increment_done(job_id)

    if timed_out:
        store.update(job_id, status="failed", error="60초 시간 제한을 초과했습니다")
    else:
        store.update(job_id, status="partial" if had_failure else "succeeded")
