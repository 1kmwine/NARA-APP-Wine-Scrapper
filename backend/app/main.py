from __future__ import annotations
import os
import threading
import time
from datetime import datetime

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
from . import briefing_summary

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
YOUTUBE_MAX_AGE_DAYS = 365 * 5


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


def _get_existing_article(url: str) -> dict | None:
    return _with_connection(lambda conn: db.get_article(conn, url))


def _find_english_name(query: str) -> str | None:
    return _with_connection(lambda conn: db.find_english_name(conn, query))


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
                # "와인"을 붙여서 검색하면 노래 제목·일반명사와 겹치는 와인명(예:
                # "베러하프")도 와인 관련 기사 위주로 나온다(구글에서 "베러하프 와인"으로
                # 검색하면 실제로 이렇게 됨 — 2026-07-22 확인). 매칭된 제품의 nameEn이
                # 검색어와 다르면(예: "Better Half") 그걸로도 한 번 더 검색해 영문
                # 표기만 쓰는 국내 기사도 잡는다.
                items = fetch_all_items(
                    f"{query} 와인", settings.naver_client_id, settings.naver_client_secret, client,
                )
                english = _find_english_name(query)
                if english and english.strip().lower() != query.strip().lower():
                    time.sleep(0.3)
                    items += fetch_all_items(
                        english, settings.naver_client_id, settings.naver_client_secret, client,
                    )
                return items

            def fetch_blog_items(query: str) -> list:
                return collectors.collect_naver_blog(
                    query, settings.naver_client_id, settings.naver_client_secret, client,
                )

            def fetch_youtube_items(source) -> list:
                # scraping-sources.md의 "최근_유튜브_일수"보다 넓게, 최근 5년까지 본다 —
                # 어차피 채널당 최신 3개만 가져오므로(collect_youtube의 videos[:3]) 너무
                # 타이트한 기간 제한이 관련 영상을 놓치는 문제가 있었다.
                return collectors.collect_youtube(source, client, max_age_days=YOUTUBE_MAX_AGE_DAYS)

            def fetch_youtube_search_items(query: str) -> list:
                return collectors.collect_youtube_search(query, client)

            def fetch_wassap_items(source) -> list:
                return collectors.search_wassap(wine_name, source, client, settings.naver_cookie)

            def _resolve_english_query() -> str:
                # 해외소스는 전부 영어라 한글 검색어를 그대로 넘기면 안 걸린다.
                # integrated_item_info(나라셀라가 실제 취급하는 상품)에 정확한
                # 영문 표기가 있으면 그걸 우선 쓴다 — 구글번역 음역(예: "케이머스"
                # → "케이무스")은 사용자가 입력한 한글 표기와 달라져서 이후
                # 재판정에 안 걸리는 문제가 있었다(2026-07-22). DB에 없는
                # 브랜드만 구글번역 폴백(collectors 내부에서 처리). run_job이
                # 실제로 international/web-search를 호출할 때만 DB를 조회하도록
                # 지연 평가한다(테스트에서 run_job을 통째로 mock하는 경우 등
                # 불필요한 DB 접근을 막기 위함).
                return _find_english_name(wine_name) or wine_name

            def fetch_international_items(source) -> list:
                return collectors.collect_international(source, client, query=_resolve_english_query())

            def fetch_web_items(query: str) -> list:
                return collectors.search_web(_resolve_english_query(), client)

            run_job(
                job_id,
                store,
                sources,
                wine_name,
                brand,
                fetch_naver_items=fetch_naver_items,
                fetch_html=fetch_html,
                get_known_brands=_get_known_brands,
                get_existing_article=_get_existing_article,
                insert_article=_insert_article,
                parse_article_meta=parse_article_meta,
                match_brands=match_brands,
                extract_visible_text=extract_visible_text,
                fetch_blog_items=fetch_blog_items,
                fetch_youtube_search_items=fetch_youtube_search_items,
                fetch_web_items=fetch_web_items,
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
            # +1은 등록 채널과 별개로 항상 도는 유튜브 검색(유튜브 결과가 0건만
            # 나오던 문제 개선) — 진행률 바의 done/total 계산에 맞춰 넣어준다.
            "youtube": len(sources.youtube) + 1,
            "wassap": len(sources.wassap),
            # +1은 등록 소스(Decanter/Wine Spectator/OIV) 3곳과 별개로 항상 도는
            # 웹 검색(DuckDuckGo) — 3곳만으론 커버리지가 너무 좁아서 추가.
            "international": len(sources.international) + 1,
            # 블로그는 등록 소스 목록이 없는 항상-켜짐 검색이라 개수 개념이 없다 —
            # 진행률 바가 다른 카테고리와 같은 방식(done/total)으로 계산하도록 1로 고정.
            "blog": 1,
        },
        "names": {
            "news": [s.name for s in sources.news],
            "youtube": [s.name for s in sources.youtube],
            "wassap": [s.name for s in sources.wassap],
            "international": [s.name for s in sources.international],
            "blog": ["네이버 블로그 전체"],
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


@app.get("/briefings/weekly-summary")
def get_weekly_summary(week_start: str):
    """docs/data/{그 주 7일}/*.json을 모아 LLM(Gemini, 무료 티어)으로 글로벌
    동향/소비자 트렌드/업계 활동 3분류 요약을 만든다. 같은 주 재요청은 fingerprint가
    같으면 캐시(docs/summaries/{week_start}.json)를 그대로 쓴다 — LLM 재호출 없음.
    GEMINI_API_KEY 미설정 시 502 — 프론트가 기존 발췌 요약으로 폴백한다."""
    try:
        start_date = datetime.strptime(week_start, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="week_start는 YYYY-MM-DD 형식이어야 합니다")
    if start_date.weekday() != 0:
        raise HTTPException(status_code=400, detail="week_start는 월요일이어야 합니다")

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=502, detail="GEMINI_API_KEY가 설정되지 않았습니다")

    try:
        return briefing_summary.build_weekly_summary(week_start, api_key)
    except Exception as exc:  # noqa: BLE001 — LLM/네트워크 오류는 폴백 대상이라 그대로 502로
        raise HTTPException(status_code=502, detail=f"주간 요약 생성 실패: {exc}") from exc
