from __future__ import annotations
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Callable, Optional

from .brand_match import fuzzy_find, fuzzy_find_all, make_context_excerpt
from .sources import SourcesConfig
from .collectors import CollectedItem
from .naver_search import items_for_domain
from .price_extraction import (
    extract_channel_prices, merge_channel_prices_by_month, resolve_single_channel,
)

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
    price_results: list[dict] = field(default_factory=list)
    price_checked_items: list[dict] = field(default_factory=list)
    # 지금 무슨 글을 보고 있는지 한 줄로 — 가격검색이 글 20~30개를 순차로 훑고
    # 이미지까지 보면 수 분이 걸려서, 진행 상황을 화면에 보여주려면 필요하다.
    progress: str = ""
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


# 검색어가 유명 와인 산지명의 앞부분과 우연히 겹치는 경우가 있다(실측 2026-07-31
# — 나라셀라가 실제 취급하는 이탈리아 와이너리 "리베라"(Rivera) 검색에 스페인 산지
# "리베라 델 두에로"(Ribera del Duero, 무관한 지역명)가 걸림). "델/디/데" 같은
# 로망스어 전치사는 진짜 브랜드명에도 흔히 쓰여서(예: Castello di Ama) 일반적인
# 패턴 규칙으론 못 거른다 — 실제로 확인된 충돌만 걸러낸다.
# ponytail: 소규모 차단목록, 새 충돌 발견 시 추가.
_REGION_NAME_FALSE_POSITIVES = (
    "리베라 델 두에로",
)


def _is_region_false_positive(text: str, match_start: int) -> bool:
    window = text[match_start:match_start + 20]
    return any(window.startswith(region) for region in _REGION_NAME_FALSE_POSITIVES)


def _matches_query(text: str, query: str) -> bool:
    """유튜브/와쌉/해외소스 콜렉터는 검색어 없이 채널·게시판·홈페이지의 최신
    항목을 그대로 가져온다 — 브랜드 매칭도 안 되고 검색어도 안 들어간 항목은
    검색과 무관한 일반 와인 소식이므로 걸러낸다. fuzzy_find를 쓰는 이유는
    _pick_highlight와 동일 — 표기 스페이싱 차이로 진짜 관련 있는 항목까지
    걸러지는 걸 막기 위해서다. 첫 매칭만 보지 않고 전체 후보를 보는 이유는
    같은 글에 진짜 매칭과 산지명 오탐이 둘 다 있을 수 있어서다."""
    query = (query or "").strip()
    if not query:
        return True
    return any(
        not _is_region_false_positive(text, m.start())
        for m in fuzzy_find_all(text, query)
    )


def _brand_relates_to_query(matched: list[str], query: str) -> bool:
    """match_brands는 회사 전체 카탈로그(수백 개 브랜드/제품명)를 대상으로 스캔하므로
    "matched가 비어있지 않다"는 이 기사에 검색어와 무관한 다른 브랜드가 하나라도
    있다는 뜻일 뿐이다(실측 2026-07-31 — "레꼴" 검색에 전혀 다른 "Fantini"/"Fonseca"가
    매칭됐다는 이유만으로 무관한 기사가 통과됨). 검색어가 matched 브랜드명 문자열
    안에(또는 그 반대로) 실제로 들어있을 때만 "이 매칭이 검색어와 관련 있다"고
    본다 — "베러하프" 검색이 DB의 "더 베터 하프 말보로 소비뇽 블랑" 같은 긴
    제품명에 부분포함되는 경우는 여전히 통과시키기 위함."""
    query = (query or "").strip()
    if not query:
        return False
    return any(fuzzy_find(brand, query) or fuzzy_find(query, brand) for brand in matched)


def _pick_highlight(text: str, query: str, matched: list[str]) -> str:
    """카드 요약에 하이라이트할 문구를 고른다 — 사용자가 실제로 입력한 검색어가
    본문에 있으면 그걸 우선하고, 없으면(브랜드 매칭만으로 결과에 포함된 경우)
    첫 번째 매칭 브랜드를 쓴다."""
    if query and fuzzy_find(text, query):
        return query
    return matched[0] if matched else ""


# "베러하프"(K팝 노래 제목이기도 함), "줄스테일러" 같은 흔한 단어/동음이의어 검색어는
# 블로그·유튜브 검색에서 와인과 무관한 진짜 콘텐츠(노래 가사, 커피숍 후기, 골프웨어
# 광고...)를 그대로 걸고 온다 — 검색엔진 입장에선 그 검색어를 문자 그대로 담고 있는
# 진짜 관련 결과라 skip_relevance_filter로도 안 걸러진다. 브랜드 매칭이 없을 때
# 최소한 와인 도메인 단어 하나는 나와야 통과시킨다.
_WINE_KEYWORDS = (
    "와인", "wine", "와이너리", "포도", "빈티지", "샴페인", "까바", "cava", "스파클링",
    "레드와인", "화이트와인", "로제", "소비뇽", "까베르네", "cabernet", "메를로", "merlot",
    "시라", "피노", "리슬링", "말벡", "템프라니요", "브뤼", "brut", "리제르바", "reserva",
    "디캔터", "소믈리에", "와인샵", "와인바", "셀러", "떼루아", "빈야드", "vineyard",
    "포도밭", "와인숍", "와인수입", "수입와인",
)


def _mentions_wine(text: str) -> bool:
    lower = text.lower()
    return any(kw in lower for kw in _WINE_KEYWORDS)


def _process_collected_item(
    job_id: str, store: JobStore, source_id: str, source_category: str,
    item: CollectedItem, known_brands: list[str], query: str,
    get_existing_article: Callable[[str], Optional[dict]], insert_article: Callable[..., int],
    match_brands: Callable[[str, list[str]], list[str]],
    skip_relevance_filter: bool = False,
    trust_source: bool = False,
) -> None:
    """유튜브/와쌉/해외소스처럼 collectors.py가 이미 title/excerpt까지 만들어 반환한
    아이템 하나를 매칭→중복확인→저장까지 처리한다 (og:meta 파싱 불필요).

    관련성 판단(matched/_matches_query)이 먼저다 — 등록 채널/해외소스처럼
    검색어 없이 채널·홈페이지 최신 항목을 그대로 반환하는 콜렉터는 같은
    URL이 예전의 다른 검색에서 이미 저장돼 있는 경우가 매우 흔하다. 중복확인을
    먼저 하면 이번 검색어와 무관한 예전 저장분까지 "중복" 카드로 전부 노출된다.

    skip_relevance_filter=True는 블로그·유튜브 검색처럼 이미 검색엔진 자체가
    query로 걸러준 결과다 — 영상 제목이 검색어를 그대로 담고 있으리라는 보장이
    없어(예: 실제로는 관련 있어도 제목이 "봄에는 이거 드세요"처럼 클릭베이트일
    수 있음) title/excerpt 텍스트만으로 재판정하면 진짜 결과까지 걸러진다. 대신
    브랜드 매칭도 없고 와인 관련 단어도 하나 없으면(_mentions_wine) 걸러낸다 —
    검색엔진이 문자 그대로는 관련 있다고 준 결과라도 와인과 전혀 무관할 수 있다.

    trust_source=True는 와쌉처럼 소스 자체가 이미 100% 와인 커뮤니티인 경우다 —
    유튜브 채널(잡다한 영상 섞임)이나 뉴스 언론사(모든 주제)와 달리, 와쌉은
    "와인 싸게 사는 사람들" 카페 전체가 와인 얘기라 게시글 하나하나의 텍스트
    관련성 재판정 자체가 무의미하다(2026-07-22 실측 — 최신 10건 중 브랜드명을
    문자 그대로 언급하는 글이 거의 없어 필터를 걸면 사실상 항상 0건이 됨).
    필터를 아예 안 걸고 다 통과시킨다."""
    matched = match_brands(f"{item.title} {item.excerpt}", known_brands)
    full_text = f"{item.title} {item.excerpt}"
    if not trust_source:
        if skip_relevance_filter:
            if not matched and not _mentions_wine(f"{full_text} {item.source_name}"):
                return
        elif not matched and not _matches_query(full_text, query):
            return

    existing = get_existing_article(item.external_url)
    if existing is not None:
        # 중복이어도 이미 새로 가져온 title/excerpt가 있으니(뉴스만 예외 — 중복이면
        # HTML을 아예 안 가져옴), 그걸로 하이라이트 중심 요약을 다시 만들고 썸네일도
        # DB에 없으면 이번에 가져온 걸로 메꾼다. DB에는 안 쓴다 — 화면 표시만 개선.
        highlight = _pick_highlight(full_text, query, matched)
        display_excerpt = make_context_excerpt(full_text, highlight, existing["excerpt"])
        store.append_result(job_id, JobResultItem(
            source_id=source_id, source_name=item.source_name, source_category=source_category,
            title=existing["title"], published_date=existing["published_date"], external_url=item.external_url,
            excerpt=display_excerpt, thumbnail_url=existing["thumbnail_url"] or item.thumbnail_url, status="중복",
            matched_brands=matched,
        ))
        return

    highlight = _pick_highlight(full_text, query, matched)
    item = replace(item, excerpt=make_context_excerpt(full_text, highlight, item.excerpt))

    insert_article(item.source_name, item.external_url, item, matched, source_category)
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
    get_existing_article: Callable[[str], Optional[dict]],
    insert_article: Callable[..., int],
    parse_article_meta: Callable[[str, str], object],
    match_brands: Callable[[str, list[str]], list[str]],
    extract_visible_text: Callable[[str], str],
    fetch_blog_items: Callable[[str], list[CollectedItem]],
    fetch_youtube_search_items: Callable[[str], list[CollectedItem]],
    fetch_web_items: Callable[[str], list[CollectedItem]],
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
                        existing = get_existing_article(url)
                        if existing is not None:
                            # HTML을 새로 안 받아오니 full_text가 없다 — 저장된
                            # title/excerpt만으로 같은 관련성 검사를 한다(등록
                            # 언론사 URL이라고 무조건 관련 있는 게 아니다).
                            existing_text = f"{existing['title']} {existing['excerpt']}"
                            existing_matched = match_brands(existing_text, known_brands)
                            if (not _matches_query(existing_text, query)
                                    and not _brand_relates_to_query(existing_matched, query)):
                                continue
                            store.append_result(job_id, JobResultItem(
                                source_id=source.id, source_name=source.name, source_category="news",
                                title=existing["title"], published_date=existing["published_date"],
                                external_url=url, excerpt=existing["excerpt"],
                                thumbnail_url=existing["thumbnail_url"], status="중복",
                                matched_brands=existing_matched,
                            ))
                            continue

                        html = fetch_html(url)
                        article = parse_article_meta(html, wine_name)
                        if not article.title:
                            raise ValueError("파싱된 제목이 비어있음")

                        full_text = f"{article.title} {extract_visible_text(html)}"
                        matched = match_brands(full_text, known_brands)
                        # 도메인 큐레이션(등록된 언론사)만으로는 관련성이 보장되지 않는다 —
                        # 애매한 검색어(예: 노래 제목과 같은 와인명)는 등록 언론사의
                        # 완전히 무관한 기사(빵 트렌드, 신곡 발매 등)까지 걸고 온다.
                        # matched는 회사 전체 카탈로그 대상 스캔이라 검색어와 무관한
                        # 다른 브랜드 하나만 우연히 있어도 채워진다 — "matched가 있다"가
                        # 아니라 "matched된 브랜드가 검색어와 실제로 관련 있다"를 봐야
                        # 한다(_brand_relates_to_query). _mentions_wine("와인"이란
                        # 단어만 있으면 통과)은 거의 모든 와인 매체 기사를 무조건
                        # 통과시켜버려서 검색어 필터 역할을 못 했다 — 제거.
                        if not _matches_query(full_text, query) and not _brand_relates_to_query(matched, query):
                            continue
                        highlight = _pick_highlight(full_text, query, matched)
                        article.excerpt = make_context_excerpt(full_text, highlight, article.excerpt)
                        insert_article(source.name, url, article, matched, "news")

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

    # ── 블로그: 뉴스처럼 등록 소스 목록이 없다(블로거가 수천 명이라 도메인
    # 큐레이션이 안 맞음) — 검색어로 딱 1번만 수집하고 done을 1만큼만 올린다 ──
    if not timed_out:
        if deadline_passed():
            timed_out = True
        else:
            try:
                blog_items = fetch_blog_items(query)
            except Exception as exc:  # noqa: BLE001
                logger.exception("블로그 수집 실패")
                had_failure = True
                store.append_result(job_id, JobResultItem(
                    source_id="naver-blog", source_name="네이버 블로그", source_category="blog",
                    title="", published_date=None, external_url="", status="실패",
                    reason=f"블로그 수집 실패: {exc}",
                ))
                blog_items = []

            for item in blog_items:
                try:
                    _process_collected_item(
                        job_id, store, "naver-blog", "blog", item, known_brands, query,
                        get_existing_article, insert_article, match_brands,
                        skip_relevance_filter=True,
                    )
                except Exception as exc:  # noqa: BLE001 — 이 아이템만 실패 처리하고 계속 진행
                    logger.exception("%s 저장 실패", item.external_url)
                    had_failure = True
                    store.append_result(job_id, JobResultItem(
                        source_id="naver-blog", source_name=item.source_name, source_category="blog",
                        title="", published_date=None, external_url=item.external_url, status="실패",
                        reason=f"저장 실패: {exc}",
                    ))
            store.increment_done(job_id)

    # ── 유튜브 검색: 등록 채널의 최신 영상만으로는 커버리지가 너무 좁아(대부분
    # 0건) 검색어로 유튜브 검색결과 자체도 긁어온다. 블로그처럼 등록 소스 목록이
    # 없는 항상-켜짐 단위라 done을 1만큼만 올린다 — 등록 채널 결과(아래 category_
    # sources 루프)와 같은 category="youtube"로 합쳐진다. ──
    if not timed_out:
        if deadline_passed():
            timed_out = True
        else:
            try:
                search_items = fetch_youtube_search_items(query)
            except Exception as exc:  # noqa: BLE001
                logger.exception("유튜브 검색 실패")
                had_failure = True
                store.append_result(job_id, JobResultItem(
                    source_id="youtube-search", source_name="YouTube 검색", source_category="youtube",
                    title="", published_date=None, external_url="", status="실패",
                    reason=f"유튜브 검색 실패: {exc}",
                ))
                search_items = []

            for item in search_items:
                try:
                    _process_collected_item(
                        job_id, store, "youtube-search", "youtube", item, known_brands, query,
                        get_existing_article, insert_article, match_brands,
                        skip_relevance_filter=True,
                    )
                except Exception as exc:  # noqa: BLE001 — 이 아이템만 실패 처리하고 계속 진행
                    logger.exception("%s 저장 실패", item.external_url)
                    had_failure = True
                    store.append_result(job_id, JobResultItem(
                        source_id="youtube-search", source_name=item.source_name, source_category="youtube",
                        title="", published_date=None, external_url=item.external_url, status="실패",
                        reason=f"저장 실패: {exc}",
                    ))
            store.increment_done(job_id)

    # ── 와쌉/해외소스: collector가 이미 완성된 아이템을 돌려준다 (등록 채널
    # 유튜브도 여기 포함 — 검색과 같은 category="youtube"로 합쳐진다) ──
    category_sources = [
        ("youtube", sources.youtube, fetch_youtube_items, False),
        # fetch_wassap_items가 이제 collect_wassap(최신글)이 아니라
        # search_wassap(검색어)를 호출한다 — 네이버 통합검색이 이미 검색어
        # 관련성을 판정해서 준 결과라 게시글 텍스트로 다시 판정 안 함.
        ("wassap", sources.wassap, fetch_wassap_items, True),
        # collect_international이 Wine Spectator/OIV는 영문 번역 검색어로 실제
        # 사이트 검색을 한다(2026-07-22) — 번역된 한글 제목("케이무스")이 원래
        # 한글 검색어("케이머스")와 표기가 달라 문자 매칭 재판정이 항상 실패하는
        # 문제가 있었다(구글번역 음역이 사용자 입력 표기와 다름). 이미 영문
        # 검색으로 관련성이 검증된 결과라 재판정 안 함. Decanter만 검색이 안 돼
        # 최신글을 그대로 주지만, 그래도 와인 전문지 콘텐츠라 무관하진 않다.
        ("international", sources.international, fetch_international_items, True),
    ]
    for category, source_list, fetch_items, trust_source in category_sources:
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
                        job_id, store, source.id, category, item, known_brands, query,
                        get_existing_article, insert_article, match_brands,
                        trust_source=trust_source,
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

    # ── 웹 검색: Decanter/Wine Spectator/OIV 3곳으로는 커버리지가 너무 좁아
    # (2026-07-22 실측 — 다수 브랜드가 3곳 다 0건) DuckDuckGo로 와인 관련 웹
    # 전체를 검색한다. 블로그/유튜브검색처럼 등록 소스 목록이 없는 항상-켜짐
    # 단위, category="international"이라 위 category_sources의 해외소스
    # 결과와 합쳐진다(진행률 바 순서를 맞추려 international 처리 바로 뒤에 둠). ──
    if not timed_out:
        if deadline_passed():
            timed_out = True
        else:
            try:
                web_items = fetch_web_items(query)
            except Exception as exc:  # noqa: BLE001
                logger.exception("웹 검색 실패")
                had_failure = True
                store.append_result(job_id, JobResultItem(
                    source_id="web-search", source_name="웹 검색", source_category="international",
                    title="", published_date=None, external_url="", status="실패",
                    reason=f"웹 검색 실패: {exc}",
                ))
                web_items = []

            for item in web_items:
                try:
                    _process_collected_item(
                        job_id, store, "web-search", "international", item, known_brands, query,
                        get_existing_article, insert_article, match_brands,
                        trust_source=True,
                    )
                except Exception as exc:  # noqa: BLE001 — 이 아이템만 실패 처리하고 계속 진행
                    logger.exception("%s 저장 실패", item.external_url)
                    had_failure = True
                    store.append_result(job_id, JobResultItem(
                        source_id="web-search", source_name=item.source_name, source_category="international",
                        title="", published_date=None, external_url=item.external_url, status="실패",
                        reason=f"저장 실패: {exc}",
                    ))
            store.increment_done(job_id)

    if timed_out:
        store.update(job_id, status="failed", error="60초 시간 제한을 초과했습니다")
    else:
        store.update(job_id, status="partial" if had_failure else "succeeded")


def run_price_job(
    job_id: str,
    store: JobStore,
    sources: SourcesConfig,
    wine_name: str,
    brand: str,
    fetch_blog_items: Callable[[str], list[CollectedItem]],
    fetch_wassap_items: Callable[[object], list[CollectedItem]],
    fetch_blog_body: Callable[[str], Optional[object]],
    fetch_wassap_body: Callable[[object, str], Optional[object]],
    insert_channel_price: Callable[[str, str, int, int, str, str, str], int],
    get_price_history: Callable[[str], list[dict]],
    extract_image_price: Callable[[list[str]], Optional[int]] | None = None,
    deadline: float | None = None,
) -> None:
    """가격검색 탭 전용 — 스크래퍼 탭(run_job)과 완전히 분리된 가벼운 흐름.
    뉴스/유튜브/해외소스는 스킵하고 블로그·와쌉 검색결과의 본문만 가져와
    가격을 추출·저장한다.

    관련성은 두 단계로 본다(2026-09-03 실측 — 네이버 블로그 검색이 "몬테스
    클래식"에 몬테스 알파·스페셜 퀴베 글까지 돌려줘서, 다른 제품 가격이 클래식
    가격으로 저장되는 문제가 있었다):
      1) 글 단위 — 제목+본문에 검색어가 (띄어쓰기 무시) 아예 없으면 그 글은
         버린다. 검색엔진이 토큰 단위로 느슨하게 매칭해 온 다른 제품 글을 여기서
         걷어낸다.
      2) 줄 단위 — extract_channel_prices(query=...)가 같은 브랜드의 다른 제품
         가격 줄을 버린다(가격비교 글 대응)."""
    store.update(job_id, status="running")
    query = brand or wine_name
    # 블로그 검색은 시음기·여행기 등 가격과 무관한 글이 대부분이라(실측: 25건 중
    # 가격 언급 2건) 검색어에 "가격"을 붙여 가격 얘기하는 글 위주로 좁힌다.
    # 와쌉은 애초에 특가/구매 글만 올라오는 카페라 그대로 검색한다 — 좁은 코퍼스에
    # "가격"까지 붙이면 0건이 되기 쉽다.
    blog_query = f"{query} 가격"
    had_failure = False
    timed_out = False
    checked_items: list[dict] = []

    def _today_year_month() -> str:
        return datetime.now().strftime("%Y-%m")

    def deadline_passed() -> bool:
        return deadline is not None and time.monotonic() > deadline

    def publish(note: str = "") -> None:
        """진행 상황과 지금까지의 목록을 화면에 즉시 반영한다. 글 하나 끝날 때마다
        불러야 프론트가 폴링할 때 실시간으로 보인다(예전엔 루프가 다 끝난 뒤
        한꺼번에 반영해서 몇 분간 빈 화면이었다)."""
        store.update(job_id, progress=note, price_checked_items=list(checked_items))

    def _shorten(text: str, limit: int = 40) -> str:
        text = (text or "").strip()
        return text if len(text) <= limit else text[:limit] + "…"

    def _normalize_body(body) -> tuple[str | None, list[str]]:
        """fetch_*_body는 FetchedBody(text, image_urls)를 돌려주지만, 문자열을
        돌려주는 호출부도 계속 지원한다(기존 테스트/호출 호환). 문자열이면
        이미지 없는 글로 본다."""
        if body is None:
            return None, []
        if isinstance(body, str):
            return body, []
        return body.text, list(body.image_urls)

    def _collect_prices(body, published_date: str | None, source_type: str,
                        source_url: str, title: str = "", entry: dict | None = None) -> str:
        """가격을 추출·저장하고, 이 글을 어떻게 처리했는지 상태 문자열을 돌려준다.
        화면의 '검색한 글' 목록에 사유를 그대로 보여주기 위한 값 —
        'no_body'(본문 못 가져옴) | 'unrelated'(검색어가 글에 없음, 다른 제품)
        | 'priced'(본문 텍스트에서 가격 저장) | 'priced_from_image'(이미지에서
        가격 저장) | 'no_price'(관련 글이지만 가격 못 찾음)."""
        body_text, image_urls = _normalize_body(body)
        if not body_text:
            return "no_body"
        if not fuzzy_find(f"{title}\n{body_text}", query):
            return "unrelated"  # 검색어가 글 어디에도 없다 — 다른 제품 글
        fallback_ym = (published_date or "")[:7] or _today_year_month()
        try:
            prices = extract_channel_prices(body_text, fallback_ym, query=query)
        except Exception:  # noqa: BLE001 — 추출 자체가 깨져도 이 소스만 생략, 검색 전체는 계속
            logger.exception("가격 추출 실패: %s", source_url)
            return "no_price"
        for p in prices:
            try:
                insert_channel_price(
                    query, p["channel"], p["price_low"], p["price_high"], p["year_month"],
                    source_type, source_url,
                )
            except Exception:  # noqa: BLE001 — DB 저장 실패는 로그만, 나머지 값 처리는 계속
                logger.exception("가격 저장 실패: %s", source_url)
        if prices:
            return "priced"
        # 본문 텍스트에 가격이 없을 때만 이미지를 본다 — 호출 최소화 + 같은
        # (source_url, channel, year_month) 키에 텍스트/이미지 값이 겹치지 않게.
        if not (extract_image_price and image_urls):
            return "no_price"
        channel = resolve_single_channel(f"{title}\n{body_text}")
        if channel is None:
            return "no_price"  # 어느 채널 가격인지 확정 불가 — 지어내지 않는다
        # 여기서부터 실제로 이미지를 내려받아 추출기를 돌린다 — 글당 수 초 걸리므로
        # 화면에 "이미지 분석 중"으로 표시하고, 결과와 무관하게 '이미지도 봤다'는
        # 사실을 목록에 남긴다(image_checked).
        if entry is not None:
            entry["image_checked"] = True
            entry["status"] = "checking_image"
            publish(f"이미지 분석 중 · {_shorten(title)}")
        try:
            image_price = extract_image_price(image_urls)
        except Exception:  # noqa: BLE001 — 이 글만 생략
            logger.exception("이미지 가격 추출 실패: %s", source_url)
            return "no_price"
        if image_price is None:
            return "no_price"
        try:
            insert_channel_price(
                query, channel, image_price, image_price, fallback_ym,
                f"{source_type}_img", source_url,
            )
        except Exception:  # noqa: BLE001
            logger.exception("이미지 가격 저장 실패: %s", source_url)
            return "no_price"
        return "priced_from_image"

    if deadline_passed():
        timed_out = True
    else:
        try:
            blog_items = fetch_blog_items(blog_query)
        except Exception as exc:  # noqa: BLE001
            logger.exception("블로그 수집 실패")
            had_failure = True
            blog_items = []

        for index, item in enumerate(blog_items, start=1):
            if deadline_passed():
                timed_out = True
                break
            entry = {
                "source_type": "blog", "source_name": item.source_name, "title": item.title,
                "external_url": item.external_url, "published_date": item.published_date,
                "status": "checking",
            }
            checked_items.append(entry)
            publish(f"블로그 {index}/{len(blog_items)} · {_shorten(item.title)}")
            try:
                entry["status"] = _collect_prices(
                    fetch_blog_body(item.external_url), item.published_date, "blog",
                    item.external_url, item.title, entry=entry)
            except Exception:  # noqa: BLE001 — fetch_blog_body 자체가 예외를 던지는 극단적 경우 대비
                logger.exception("블로그 본문 가져오기 실패: %s", item.external_url)
                entry["status"] = "no_body"
            publish(f"블로그 {index}/{len(blog_items)} · {_shorten(item.title)}")
        store.increment_done(job_id)

    for source in sources.wassap:
        if timed_out or deadline_passed():
            timed_out = True
            break
        try:
            wassap_items = fetch_wassap_items(source)
        except Exception as exc:  # noqa: BLE001
            logger.exception("와쌉(%s) 수집 실패", source.name)
            had_failure = True
            store.increment_done(job_id)
            continue

        for index, item in enumerate(wassap_items, start=1):
            if deadline_passed():
                timed_out = True
                break
            entry = {
                "source_type": "wassap", "source_name": item.source_name, "title": item.title,
                "external_url": item.external_url, "published_date": item.published_date,
                "status": "checking",
            }
            checked_items.append(entry)
            publish(f"와쌉 {index}/{len(wassap_items)} · {_shorten(item.title)}")
            try:
                entry["status"] = _collect_prices(
                    fetch_wassap_body(source, item.external_url), item.published_date, "wassap",
                    item.external_url, item.title, entry=entry)
            except Exception:  # noqa: BLE001
                logger.exception("와쌉 본문 가져오기 실패: %s", item.external_url)
                entry["status"] = "no_body"
            publish(f"와쌉 {index}/{len(wassap_items)} · {_shorten(item.title)}")
        store.increment_done(job_id)

    try:
        history_rows = get_price_history(query)
        store.update(job_id, price_results=merge_channel_prices_by_month(history_rows))
    except Exception as exc:  # noqa: BLE001 — 이력 조회 실패는 화면에 빈 결과로 남기고 partial 처리
        logger.exception("가격 이력 조회 실패")
        had_failure = True

    if timed_out:
        # 제한 시간은 호출부(main.py)가 정하므로 메시지에 초를 하드코딩하지 않는다.
        # 중간까지 확인한 게 있으면 그것까지는 살려서 partial로 돌려준다 —
        # 예전엔 통째로 failed라 20개 중 18개를 봤어도 결과가 안 보였다.
        store.update(job_id, status="partial" if checked_items else "failed",
                     progress="", error="시간 제한을 초과해 중간까지만 확인했습니다")
    else:
        store.update(job_id, status="partial" if had_failure else "succeeded", progress="")
