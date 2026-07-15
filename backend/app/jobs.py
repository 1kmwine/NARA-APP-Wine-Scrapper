from __future__ import annotations
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Optional

from .sources import Source

logger = logging.getLogger(__name__)


@dataclass
class JobResultItem:
    source_id: str
    source_name: str
    title: str
    published_date: Optional[str]
    external_url: str
    status: str  # '저장됨' | '중복' | '실패'
    matched_brands: list[str] = field(default_factory=list)


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


def run_job(
    job_id: str,
    store: JobStore,
    sources: list[Source],
    wine_name: str,
    brand: str,
    search_urls_for_domain: Callable[[str, str], list[str]],
    fetch_html: Callable[[str], str],
    get_known_brands: Callable[[], list[str]],
    article_exists: Callable[[str], bool],
    insert_article: Callable[..., int],
    parse_article_meta: Callable[[str, str], object],
    match_brands: Callable[[str, list[str]], list[str]],
    extract_visible_text: Callable[[str], str],
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

    for source in sources:
        if deadline is not None and time.monotonic() > deadline:
            timed_out = True
            break

        try:
            urls = search_urls_for_domain(query, source.domain)
        except Exception as exc:  # noqa: BLE001
            logger.exception("%s 소스 검색 실패", source.name)
            had_failure = True
            store.append_result(
                job_id,
                JobResultItem(
                    source_id=source.id,
                    source_name=source.name,
                    title=f"{source.name} 검색 실패: {exc}",
                    published_date=None,
                    external_url="",
                    status="실패",
                ),
            )
            store.increment_done(job_id)
            continue

        for url in urls:
            if deadline is not None and time.monotonic() > deadline:
                timed_out = True
                break

            try:
                if article_exists(url):
                    store.append_result(
                        job_id,
                        JobResultItem(
                            source_id=source.id,
                            source_name=source.name,
                            title=url,
                            published_date=None,
                            external_url=url,
                            status="중복",
                        ),
                    )
                    continue

                html = fetch_html(url)
                article = parse_article_meta(html, wine_name)
                if not article.title:
                    raise ValueError("파싱된 제목이 비어있음")

                full_text = f"{article.title} {extract_visible_text(html)}"
                matched = match_brands(full_text, known_brands)
                insert_article(source.name, url, article, matched)

                store.append_result(
                    job_id,
                    JobResultItem(
                        source_id=source.id,
                        source_name=source.name,
                        title=article.title,
                        published_date=article.published_date,
                        external_url=url,
                        status="저장됨",
                        matched_brands=matched,
                    ),
                )
            except Exception as exc:  # noqa: BLE001 — 이 URL만 실패 처리하고 계속 진행
                logger.exception("%s 처리 실패", url)
                had_failure = True
                store.append_result(
                    job_id,
                    JobResultItem(
                        source_id=source.id,
                        source_name=source.name,
                        title=f"{url} (실패: {exc})",
                        published_date=None,
                        external_url=url,
                        status="실패",
                    ),
                )

        store.increment_done(job_id)

        if timed_out:
            break

    if timed_out:
        store.update(job_id, status="failed", error="60초 시간 제한을 초과했습니다")
    else:
        store.update(job_id, status="partial" if had_failure else "succeeded")
