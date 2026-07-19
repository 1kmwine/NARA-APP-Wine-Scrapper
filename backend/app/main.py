from __future__ import annotations
import threading
import time

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .config import get_settings
from .naver_search import fetch_all_items
from .parse import parse_article_meta, extract_visible_text
from .brand_match import match_brands
from .jobs import JobStore, run_job
from . import db
from . import source_config
from . import collectors

app = FastAPI(title="NARA Wine Scraper API")
# 이 서비스는 127.0.0.1에만 바인딩되어 nginx 리버스 프록시를 통해서만 접근되고
# 인터넷에 직접 노출되지 않으므로, 모든 origin을 허용해도 안전하다.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

store = JobStore()
settings = get_settings()


class CreateJobRequest(BaseModel):
    wine_name: str
    brand: str = ""


class CreateJobResponse(BaseModel):
    job_id: str


class AddSourceRequest(BaseModel):
    category: str  # 'news' | 'youtube' | 'wassap' | 'international'
    press: str = ""
    news_category: str = ""
    query: str = ""
    url: str = ""
    channel_name: str = ""
    channel_id: str = ""
    clubid: str = ""
    source_name: str = ""
    note: str = ""


def _with_connection(fn):
    conn = db.get_connection(
        settings.db_host, settings.db_port, settings.db_username, settings.db_password, settings.db_database
    )
    try:
        return fn(conn)
    finally:
        conn.close()


def _get_known_brands() -> list[str]:
    return _with_connection(db.get_known_brands)


def _article_exists(url: str) -> bool:
    return _with_connection(lambda conn: db.article_exists(conn, url))


def _insert_article(source_name: str, url: str, article, matched: list[str]) -> int:
    return _with_connection(lambda conn: db.insert_article(conn, source_name, url, article, matched))


def _load_current_sources():
    with httpx.Client() as client:
        return source_config.load_sources(client, settings.github_token)


def _run_job_in_background(job_id: str, sources, wine_name: str, brand: str) -> None:
    """백그라운드 스레드 진입점. job 하나의 전체 수명 동안 httpx.Client를 하나만 열어 재사용한다."""
    try:
        with httpx.Client(follow_redirects=True, timeout=15.0) as client:

            def fetch_html(url: str) -> str:
                response = client.get(url)
                response.raise_for_status()
                return response.text

            def fetch_naver_items(query: str) -> list[dict]:
                return fetch_all_items(query, settings.naver_client_id, settings.naver_client_secret, client)

            def fetch_youtube_items(source) -> list:
                return collectors.collect_youtube(source, client, max_age_days=sources.age_youtube)

            def fetch_wassap_items(source) -> list:
                return collectors.collect_wassap(source, client, settings.naver_cookie)

            def fetch_international_items(source) -> list:
                return collectors.collect_international(source, client)

            run_job(
                job_id,
                store,
                sources,
                wine_name,
                brand,
                fetch_naver_items=fetch_naver_items,
                fetch_html=fetch_html,
                get_known_brands=_get_known_brands,
                article_exists=_article_exists,
                insert_article=_insert_article,
                parse_article_meta=parse_article_meta,
                match_brands=match_brands,
                extract_visible_text=extract_visible_text,
                fetch_youtube_items=fetch_youtube_items,
                fetch_wassap_items=fetch_wassap_items,
                fetch_international_items=fetch_international_items,
                deadline=time.monotonic() + 60,
            )
    except Exception as exc:  # noqa: BLE001 — run_job 내부에서 못 잡은 예외까지 대비하는 방어 레이어
        store.update(job_id, status="failed", error=f"예기치 못한 오류: {exc}")


@app.post("/jobs", response_model=CreateJobResponse)
def create_job(payload: CreateJobRequest) -> CreateJobResponse:
    if not payload.wine_name.strip():
        raise HTTPException(status_code=400, detail="와인명을 입력해주세요")

    wine_name = payload.wine_name.strip()
    brand = payload.brand.strip()

    try:
        sources = _load_current_sources()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"소스 설정을 불러오지 못했습니다: {exc}") from exc

    if sources.total_count() == 0:
        raise HTTPException(status_code=400, detail="설정된 소스가 없습니다")

    job = store.create(wine_name, brand, total=sources.total_count())
    thread = threading.Thread(
        target=_run_job_in_background,
        args=(job.id, sources, wine_name, brand),
        daemon=True,
    )
    thread.start()
    return CreateJobResponse(job_id=job.id)


@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job을 찾을 수 없습니다")
    return {
        "job_id": job.id,
        "status": job.status,
        "total": job.total,
        "done": job.done,
        "error": job.error,
        "results": [
            {
                "source_id": r.source_id,
                "source_name": r.source_name,
                "source_category": r.source_category,
                "title": r.title,
                "excerpt": r.excerpt,
                "thumbnail_url": r.thumbnail_url,
                "published_date": r.published_date,
                "external_url": r.external_url,
                "status": r.status,
                "matched_brands": r.matched_brands,
            }
            for r in job.results if r.status != "실패"
        ],
        "failures": [
            {"source_name": r.source_name, "source_category": r.source_category, "reason": r.reason}
            for r in job.results if r.status == "실패"
        ],
    }


@app.get("/sources")
def get_sources():
    try:
        sources = _load_current_sources()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"소스 설정을 불러오지 못했습니다: {exc}") from exc
    return {
        "counts": {
            "news": len(sources.news),
            "youtube": len(sources.youtube),
            "wassap": len(sources.wassap),
            "international": len(sources.international),
        },
        "names": {
            "news": [s.name for s in sources.news],
            "youtube": [s.name for s in sources.youtube],
            "wassap": [s.name for s in sources.wassap],
            "international": [s.name for s in sources.international],
        },
    }


@app.post("/sources")
def add_source(payload: AddSourceRequest):
    client = httpx.Client()
    try:
        if payload.category == "news":
            if not (payload.press and payload.query and payload.url):
                raise HTTPException(status_code=400, detail="매체명/검색어/URL을 모두 입력해주세요")
            source_config.add_news_source(
                client, settings.github_token, press=payload.press,
                category=payload.news_category or "뉴스", query=payload.query, url=payload.url,
            )
        elif payload.category == "youtube":
            if not (payload.channel_name and payload.url):
                raise HTTPException(status_code=400, detail="채널명/URL을 입력해주세요")
            channel_id = payload.channel_id
            if not channel_id:
                import re
                handle_match = re.search(r'youtube\.com/@([\w.-]+)', payload.url)
                if handle_match:
                    channel_id = collectors.resolve_channel_id(handle_match.group(1), client)
                if not channel_id:
                    raise HTTPException(
                        status_code=400,
                        detail="Channel ID를 자동으로 찾지 못했습니다. 직접 입력해주세요",
                    )
            source_config.add_youtube_source(
                client, settings.github_token, name=payload.channel_name, url=payload.url, channel_id=channel_id,
            )
        elif payload.category == "wassap":
            if not (payload.url and payload.clubid):
                raise HTTPException(status_code=400, detail="카페 URL/clubid를 입력해주세요")
            source_config.add_wassap_source(client, settings.github_token, url=payload.url, clubid=payload.clubid)
        elif payload.category == "international":
            if not (payload.source_name and payload.url):
                raise HTTPException(status_code=400, detail="소스명/URL을 입력해주세요")
            source_config.add_international_source(
                client, settings.github_token, name=payload.source_name, url=payload.url, note=payload.note,
            )
        else:
            raise HTTPException(status_code=400, detail=f"알 수 없는 카테고리: {payload.category}")
    except source_config.DuplicateSourceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except source_config.SourcesWriteConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    finally:
        client.close()
    return {"ok": True}
