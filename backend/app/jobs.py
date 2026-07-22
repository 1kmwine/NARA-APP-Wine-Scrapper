from __future__ import annotations
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field, replace
from typing import Callable, Optional

from .brand_match import fuzzy_find, make_context_excerpt
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


def _matches_query(text: str, query: str) -> bool:
    """유튜브/와쌉/해외소스 콜렉터는 검색어 없이 채널·게시판·홈페이지의 최신
    항목을 그대로 가져온다 — 브랜드 매칭도 안 되고 검색어도 안 들어간 항목은
    검색과 무관한 일반 와인 소식이므로 걸러낸다. fuzzy_find를 쓰는 이유는
    _pick_highlight와 동일 — 표기 스페이싱 차이로 진짜 관련 있는 항목까지
    걸러지는 걸 막기 위해서다."""
    query = (query or "").strip()
    return not query or bool(fuzzy_find(text, query))


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
    get_existing_article: Callable[[str], Optional[dict]],
    insert_article: Callable[..., int],
    parse_article_meta: Callable[[str, str], object],
    match_brands: Callable[[str, list[str]], list[str]],
    extract_visible_text: Callable[[str], str],
    fetch_blog_items: Callable[[str], list[CollectedItem]],
    fetch_youtube_search_items: Callable[[str], list[CollectedItem]],
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
                            if (not existing_matched and not _mentions_wine(existing_text)
                                    and not _matches_query(existing_text, query)):
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
                        # 브랜드/제품명 매칭도 없고 와인 관련 단어도 없고 검색어 자체도
                        # 안 보이면 조용히 건너뛴다(실패 아님, 그냥 무관한 것).
                        if not matched and not _mentions_wine(full_text) and not _matches_query(full_text, query):
                            continue
                        highlight = _pick_highlight(full_text, query, matched)
                        article.excerpt = make_context_excerpt(full_text, highlight, article.excerpt)
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
        # 와쌉은 "와인 싸게 사는 사람들" 카페 전체가 와인 얘기라 소스 자체가
        # 이미 100% 걸러져 있다 — 게시글 텍스트로 다시 관련성 판정 안 함.
        ("wassap", sources.wassap, fetch_wassap_items, True),
        ("international", sources.international, fetch_international_items, False),
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

    if timed_out:
        store.update(job_id, status="failed", error="60초 시간 제한을 초과했습니다")
    else:
        store.update(job_id, status="partial" if had_failure else "succeeded")
