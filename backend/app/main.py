from __future__ import annotations
import threading
import time

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .config import get_settings
from .sources import source_by_id
from .naver_search import search_urls_for_domain
from .parse import parse_article_meta, extract_visible_text
from .brand_match import match_brands
from .jobs import JobStore, run_job
from . import db

app = FastAPI(title="NARA Wine Scraper API")
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
    source_ids: list[str]


class CreateJobResponse(BaseModel):
    job_id: str


def _fetch_html(url: str) -> str:
    with httpx.Client(follow_redirects=True, timeout=15.0) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.text


def _search_urls_for_domain(query: str, domain: str) -> list[str]:
    with httpx.Client() as client:
        return search_urls_for_domain(
            query, domain, settings.naver_client_id, settings.naver_client_secret, client
        )


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


@app.post("/jobs", response_model=CreateJobResponse)
def create_job(payload: CreateJobRequest) -> CreateJobResponse:
    if not payload.wine_name.strip():
        raise HTTPException(status_code=400, detail="와인명을 입력해주세요")

    selected = [source_by_id(sid) for sid in payload.source_ids]
    selected = [s for s in selected if s is not None]
    if not selected:
        raise HTTPException(status_code=400, detail="선택된 소스가 없습니다")

    job = store.create(payload.wine_name, payload.brand, total=len(selected))
    thread = threading.Thread(
        target=run_job,
        args=(job.id, store, selected, payload.wine_name, payload.brand),
        kwargs=dict(
            search_urls_for_domain=_search_urls_for_domain,
            fetch_html=_fetch_html,
            get_known_brands=_get_known_brands,
            article_exists=_article_exists,
            insert_article=_insert_article,
            parse_article_meta=parse_article_meta,
            match_brands=match_brands,
            extract_visible_text=extract_visible_text,
            deadline=time.monotonic() + 60,
        ),
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
                "title": r.title,
                "published_date": r.published_date,
                "external_url": r.external_url,
                "status": r.status,
                "matched_brands": r.matched_brands,
            }
            for r in job.results
        ],
    }
