import time

import pytest

from app.jobs import JobStore, run_job
from app.sources import NewsSource, YoutubeSource, WassapSource, InternationalSource, SourcesConfig
from app.collectors import CollectedItem


class _Article:
    def __init__(self):
        self.title = "제목"
        self.excerpt = "요약"
        self.thumbnail_url = None
        self.published_date = "2026-07-01"


def _empty_sources(**overrides) -> SourcesConfig:
    base = dict(news=[], youtube=[], wassap=[], international=[], age_youtube=7)
    base.update(overrides)
    return SourcesConfig(**base)


def _news_deps(**overrides):
    deps = dict(
        fetch_naver_items=lambda query: [],
        fetch_html=lambda url: "<html></html>",
        get_known_brands=lambda: ["몬테스"],
        get_existing_article=lambda url: None,
        insert_article=lambda source_name, url, article, matched: 1,
        parse_article_meta=lambda html, fallback: _Article(),
        match_brands=lambda text, brands: ["몬테스"],
        extract_visible_text=lambda html: "본문",
        fetch_blog_items=lambda query: [],
        fetch_youtube_search_items=lambda query: [],
        fetch_youtube_items=lambda source: [],
        fetch_wassap_items=lambda source: [],
        fetch_international_items=lambda source: [],
    )
    deps.update(overrides)
    return deps


def test_run_job_succeeds_with_only_news_source():
    store = JobStore()
    job = store.create("몬테스", "몬테스", total=1)
    sources = _empty_sources(news=[NewsSource(id="wine21.com", name="와인21", domain="wine21.com", query="와인21")])

    run_job(job.id, store, sources, "몬테스", "몬테스", **_news_deps(
        fetch_naver_items=lambda query: [{"title": "a", "link": "https://wine21.com/1", "originallink": ""}],
    ))

    result = store.get(job.id)
    assert result.status == "succeeded"
    assert result.done == 3  # 뉴스 소스 1개 + 블로그 검색 1 + 유튜브 검색 1(항상 켜짐)
    assert len(result.results) == 1
    assert result.results[0].status == "저장됨"
    assert result.results[0].source_category == "news"
    assert result.results[0].excerpt == "요약"


def test_run_job_news_article_unrelated_to_query_is_skipped():
    # 등록 언론사 도메인이라고 해서 관련 있는 게 아니다 — 애매한 검색어("베러하프"
    # 같은 노래 제목과 겹치는 와인명)는 그 언론사의 완전히 무관한 기사(빵 트렌드
    # 등)도 걸고 올 수 있다. 브랜드 매칭도, 와인 단어도, 검색어 자체도 없으면
    # 조용히 건너뛰어야 한다(실패로 안 잡힘).
    class UnrelatedArticle:
        title = "피할 수 없지만, 늦출 수는 있다...식탁 위 저속노화 트렌드"
        excerpt = "젊어 보이는 외모보다 지속 가능한 건강이 더 중요한 가치로 떠오르며"
        thumbnail_url = None
        published_date = "2026-07-20"

    store = JobStore()
    job = store.create("베러하프", "베러하프", total=1)
    sources = _empty_sources(news=[NewsSource(id="metro.co.kr", name="메트로신문", domain="metro.co.kr", query="")])

    run_job(job.id, store, sources, "베러하프", "베러하프", **_news_deps(
        fetch_naver_items=lambda query: [{"title": "a", "link": "https://metro.co.kr/1", "originallink": ""}],
        parse_article_meta=lambda html, fallback: UnrelatedArticle(),
        match_brands=lambda text, brands: [],
    ))

    result = store.get(job.id)
    assert result.status == "succeeded"
    assert result.results == []


def test_run_job_news_duplicate_unrelated_to_query_is_skipped():
    store = JobStore()
    job = store.create("베러하프", "베러하프", total=1)
    sources = _empty_sources(news=[NewsSource(id="metro.co.kr", name="메트로신문", domain="metro.co.kr", query="")])

    run_job(job.id, store, sources, "베러하프", "베러하프", **_news_deps(
        fetch_naver_items=lambda query: [{"title": "a", "link": "https://metro.co.kr/1", "originallink": ""}],
        get_existing_article=lambda url: {
            "title": "식탁 위 저속노화 트렌드", "excerpt": "빵과 건강", "thumbnail_url": None, "published_date": None,
        },
        match_brands=lambda text, brands: [],
    ))

    result = store.get(job.id)
    assert result.results == []


def test_run_job_news_search_failure_marks_all_news_sources_failed():
    store = JobStore()
    job = store.create("몬테스", "몬테스", total=2)
    sources = _empty_sources(news=[
        NewsSource(id="wine21.com", name="와인21", domain="wine21.com", query="와인21"),
        NewsSource(id="winein.co.kr", name="와인인", domain="winein.co.kr", query="와인인"),
    ])

    def broken_fetch(query):
        raise RuntimeError("naver api 오류")

    run_job(job.id, store, sources, "몬테스", "몬테스", **_news_deps(fetch_naver_items=broken_fetch))

    result = store.get(job.id)
    assert result.status == "partial"
    assert result.done == 4  # 뉴스 소스 2개 + 블로그 검색 1 + 유튜브 검색 1(항상 켜짐)
    assert all(r.status == "실패" for r in result.results)
    assert all(r.reason for r in result.results)


def test_run_job_youtube_source_saves_prebuilt_items():
    store = JobStore()
    job = store.create("몬테스", "몬테스", total=1)
    sources = _empty_sources(youtube=[YoutubeSource(id="bimirya", name="비밀이야", handle="bimirya", channel_id="UCx")])
    item = CollectedItem(
        title="몬테스 알파 리뷰", excerpt="시음 영상", thumbnail_url=None,
        external_url="https://youtu.be/abc", published_date="2026-07-10", source_name="YouTube: 비밀이야",
    )

    run_job(job.id, store, sources, "몬테스", "몬테스", **_news_deps(
        fetch_youtube_items=lambda source: [item],
        match_brands=lambda text, brands: ["몬테스"],
    ))

    result = store.get(job.id)
    assert result.status == "succeeded"
    assert result.done == 3  # 유튜브 소스 1개 + 블로그 검색 1 + 유튜브 검색 1(항상 켜짐)
    assert result.results[0].source_category == "youtube"
    assert result.results[0].title == "몬테스 알파 리뷰"
    assert result.results[0].matched_brands == ["몬테스"]


def test_run_job_youtube_item_excerpt_rebuilt_around_query_match():
    # 원본 excerpt엔 검색어가 없고 뒤쪽 본문에만 있는 경우, 카드에 보여줄 excerpt를
    # 검색어 주변으로 다시 잘라줘야 한다 — 안 그러면 왜 매칭됐는지 안 보인다.
    store = JobStore()
    job = store.create("몬테스", "몬테스", total=1)
    sources = _empty_sources(youtube=[YoutubeSource(id="bimirya", name="비밀이야", handle="bimirya", channel_id="UCx")])
    long_excerpt = ("도입부 " * 20) + "이번 영상에서는 몬테스 알파 M을 시음한다 " + ("마무리 " * 20)
    item = CollectedItem(
        title="이번 주 와인 영상", excerpt=long_excerpt, thumbnail_url=None,
        external_url="https://youtu.be/abc", published_date="2026-07-10", source_name="YouTube: 비밀이야",
    )

    run_job(job.id, store, sources, "몬테스", "몬테스", **_news_deps(
        fetch_youtube_items=lambda source: [item],
        match_brands=lambda text, brands: [],
    ))

    result = store.get(job.id)
    assert "몬테스" in result.results[0].excerpt


def test_run_job_youtube_item_unrelated_to_query_is_dropped():
    # 유튜브/와쌉/해외소스 콜렉터는 검색어 없이 채널의 최신 영상을 그대로 반환하므로,
    # 검색어와 무관한(브랜드도 매칭 안 되는) 항목은 결과에서 걸러져야 한다.
    store = JobStore()
    job = store.create("몬테스", "몬테스", total=1)
    sources = _empty_sources(youtube=[YoutubeSource(id="bimirya", name="비밀이야", handle="bimirya", channel_id="UCx")])
    item = CollectedItem(
        title="치킨 먹으러 홍콩 워크숍", excerpt="맛집 탐방", thumbnail_url=None,
        external_url="https://youtu.be/xyz", published_date="2026-07-10", source_name="YouTube: 비밀이야",
    )

    run_job(job.id, store, sources, "몬테스", "몬테스", **_news_deps(
        fetch_youtube_items=lambda source: [item],
        match_brands=lambda text, brands: [],
    ))

    result = store.get(job.id)
    assert result.status == "succeeded"
    assert result.done == 3  # 유튜브 소스 1개 + 블로그 검색 1 + 유튜브 검색 1(항상 켜짐)
    assert result.results == []


def test_run_job_blog_item_saved_and_counted_as_one_unit():
    # 블로그·유튜브 검색은 등록 소스 목록이 없다 — sources가 전부 비어 있어도
    # 검색어로 1회씩 실행되고, done/total에도 각각 1만큼만 반영돼야 한다.
    store = JobStore()
    job = store.create("몬테스", "몬테스", total=1)
    sources = _empty_sources()
    item = CollectedItem(
        title="몬테스 알파 후기", excerpt="시음기", thumbnail_url=None,
        external_url="https://blog.naver.com/x/1", published_date="2026-07-20", source_name="블로그: x",
    )

    run_job(job.id, store, sources, "몬테스", "몬테스", **_news_deps(
        fetch_blog_items=lambda query: [item],
        match_brands=lambda text, brands: ["몬테스"],
    ))

    result = store.get(job.id)
    assert result.status == "succeeded"
    assert result.done == 2  # 블로그 검색 1 + 유튜브 검색 1(항상 켜짐)
    assert len(result.results) == 1
    assert result.results[0].source_category == "blog"
    assert result.results[0].title == "몬테스 알파 후기"


def test_run_job_blog_item_saved_even_without_literal_query_match():
    # 블로그는 네이버 검색 자체가 이미 query로 걸러준 결과다 — youtube-search와
    # 마찬가지로 title/excerpt에 검색어가 문자 그대로 없어도(브랜드 매칭도 없어도)
    # 걸러지면 안 된다. 안 그러면 실제로 관련 있는 결과까지 다 날아간다.
    store = JobStore()
    job = store.create("로저구라트", "로저구라트", total=1)
    sources = _empty_sources()
    item = CollectedItem(
        title="여름휴가 스파클링 와인 추천 6선", excerpt="", thumbnail_url=None,
        external_url="https://blog.naver.com/x/2", published_date="2026-07-20", source_name="블로그: x",
    )

    run_job(job.id, store, sources, "로저구라트", "로저구라트", **_news_deps(
        fetch_blog_items=lambda query: [item],
        match_brands=lambda text, brands: [],
    ))

    result = store.get(job.id)
    assert len(result.results) == 1
    assert result.results[0].source_category == "blog"


def test_run_job_youtube_search_item_saved_even_without_literal_query_match():
    # 유튜브 검색 결과도 마찬가지 — 영상 제목이 클릭베이트라 검색어를 그대로
    # 담고 있지 않아도(실제 영상 내용은 검색어와 관련 있음) 걸러지면 안 된다.
    # 단, 와인 얘기라는 단서(_mentions_wine)는 있어야 한다 — 아예 없으면 아래
    # test_run_job_youtube_search_item_without_query_or_wine_keyword_is_dropped 참고.
    store = JobStore()
    job = store.create("로저구라트", "로저구라트", total=1)
    sources = _empty_sources()
    item = CollectedItem(
        title="봄에는 그냥 이 와인 드세요", excerpt="", thumbnail_url=None,
        external_url="https://youtu.be/clickbait", published_date="2026-07-20", source_name="YouTube: 검색채널",
    )

    run_job(job.id, store, sources, "로저구라트", "로저구라트", **_news_deps(
        fetch_youtube_search_items=lambda query: [item],
        match_brands=lambda text, brands: [],
    ))

    result = store.get(job.id)
    assert len(result.results) == 1


def test_run_job_youtube_search_item_without_query_or_wine_keyword_is_dropped():
    # "베러하프"(K팝 노래 제목)처럼 흔한 검색어가 와인과 무관한 콘텐츠를 그대로
    # 걸고 오는 경우 — 문자 그대로는 검색어를 담고 있어도 브랜드 매칭도 없고
    # 와인 관련 단어도 하나 없으면 걸러져야 한다.
    store = JobStore()
    job = store.create("베러하프", "베러하프", total=1)
    sources = _empty_sources()
    item = CollectedItem(
        title="JEONGHAN (정한) feat. Omoinotake - 베러하프 [가사]", excerpt="", thumbnail_url=None,
        external_url="https://youtu.be/song", published_date="2026-07-20", source_name="YouTube: Music Time",
    )

    run_job(job.id, store, sources, "베러하프", "베러하프", **_news_deps(
        fetch_youtube_search_items=lambda query: [item],
        match_brands=lambda text, brands: [],
    ))

    result = store.get(job.id)
    assert result.results == []


def test_run_job_blog_fetch_failure_marked_and_isolated():
    store = JobStore()
    job = store.create("몬테스", "몬테스", total=1)
    sources = _empty_sources()

    def broken_blog(query):
        raise RuntimeError("blog api 오류")

    run_job(job.id, store, sources, "몬테스", "몬테스", **_news_deps(fetch_blog_items=broken_blog))

    result = store.get(job.id)
    assert result.status == "partial"
    assert result.done == 2  # 블로그 검색 1(실패) + 유튜브 검색 1(항상 켜짐)
    blog_result = next(r for r in result.results if r.source_category == "blog")
    assert blog_result.status == "실패"


def test_run_job_youtube_search_item_saved_alongside_channel_results():
    # 등록 채널 결과가 하나도 없어도(sources 전부 비어있음) 유튜브 검색은
    # 항상 돌고, 채널 결과와 같은 category="youtube"로 합쳐져야 한다.
    store = JobStore()
    job = store.create("몬테스", "몬테스", total=1)
    sources = _empty_sources()
    item = CollectedItem(
        title="몬테스 시음 영상", excerpt="", thumbnail_url="https://i.ytimg.com/vi/x/hq.jpg",
        external_url="https://youtu.be/x", published_date="2026-07-20", source_name="YouTube: 검색채널",
    )

    run_job(job.id, store, sources, "몬테스", "몬테스", **_news_deps(
        fetch_youtube_search_items=lambda query: [item],
        match_brands=lambda text, brands: ["몬테스"],
    ))

    result = store.get(job.id)
    assert result.status == "succeeded"
    assert result.done == 2  # 블로그 검색 1 + 유튜브 검색 1(항상 켜짐)
    assert len(result.results) == 1
    assert result.results[0].source_category == "youtube"
    assert result.results[0].title == "몬테스 시음 영상"
    assert result.results[0].thumbnail_url == "https://i.ytimg.com/vi/x/hq.jpg"


def test_run_job_youtube_search_failure_isolated_from_channel_loop():
    store = JobStore()
    job = store.create("몬테스", "몬테스", total=1)
    sources = _empty_sources(youtube=[YoutubeSource(id="bimirya", name="비밀이야", handle="bimirya", channel_id="UCx")])
    channel_item = CollectedItem(
        title="몬테스 채널 영상", excerpt="", thumbnail_url=None,
        external_url="https://youtu.be/ch1", published_date="2026-07-20", source_name="YouTube: 비밀이야",
    )

    def broken_search(query):
        raise RuntimeError("검색 실패")

    run_job(job.id, store, sources, "몬테스", "몬테스", **_news_deps(
        fetch_youtube_search_items=broken_search,
        fetch_youtube_items=lambda source: [channel_item],
        match_brands=lambda text, brands: ["몬테스"],
    ))

    result = store.get(job.id)
    assert result.status == "partial"
    saved = [r for r in result.results if r.status == "저장됨"]
    failed = [r for r in result.results if r.status == "실패"]
    assert len(saved) == 1 and saved[0].title == "몬테스 채널 영상"
    assert len(failed) == 1 and failed[0].source_category == "youtube"


def test_run_job_wassap_item_saved_even_without_query_or_brand_match():
    # 와쌉은 카페 전체가 와인 커뮤니티라 소스 자체로 이미 관련성이 보장된다 —
    # 최신 10건 중 검색어를 문자 그대로 담은 글이 거의 없어서(2026-07-22 실측),
    # 다른 콜렉터처럼 텍스트 재판정을 걸면 사실상 항상 0건이 된다.
    store = JobStore()
    job = store.create("몬테스", "몬테스", total=1)
    sources = _empty_sources(wassap=[WassapSource(id="winerack24-1", name="와쌉", cafe_id="winerack24", clubid="1")])
    item = CollectedItem(
        title="GS 8월 행사 품목", excerpt="", thumbnail_url=None,
        external_url="https://cafe.naver.com/winerack24/999", published_date=None, source_name="와쌉",
    )

    run_job(job.id, store, sources, "몬테스", "몬테스", **_news_deps(
        fetch_wassap_items=lambda source: [item],
        match_brands=lambda text, brands: [],
    ))

    result = store.get(job.id)
    assert len(result.results) == 1
    assert result.results[0].status == "저장됨"
    assert result.results[0].source_category == "wassap"


def test_run_job_wassap_duplicate_item_not_reinserted():
    store = JobStore()
    job = store.create("몬테스", "몬테스", total=1)
    sources = _empty_sources(wassap=[WassapSource(id="winerack24-1", name="와쌉", cafe_id="winerack24", clubid="1")])
    item = CollectedItem(
        title="몬테스 궁금해요", excerpt="", thumbnail_url=None,
        external_url="https://cafe.naver.com/winerack24/1", published_date=None, source_name="와쌉",
    )
    insert_calls = []

    run_job(job.id, store, sources, "몬테스", "몬테스", **_news_deps(
        fetch_wassap_items=lambda source: [item],
        get_existing_article=lambda url: {
            "title": "몬테스 궁금해요", "excerpt": "", "thumbnail_url": None, "published_date": None,
        },
        insert_article=lambda *a, **k: insert_calls.append(1) or 1,
    ))

    result = store.get(job.id)
    assert result.results[0].status == "중복"
    assert insert_calls == []


def test_run_job_wassap_duplicate_recomputes_excerpt_and_backfills_thumbnail():
    # 예전에 저장된 항목은 DB에 하이라이트 중심 요약도, 썸네일도 없을 수 있다
    # (그 기능들이 생기기 전 저장분) — 중복이어도 이번에 새로 가져온 title/excerpt/
    # thumbnail로 화면 표시만 개선해야 한다(DB는 안 건드림).
    store = JobStore()
    job = store.create("몬테스", "몬테스", total=1)
    sources = _empty_sources(wassap=[WassapSource(id="winerack24-1", name="와쌉", cafe_id="winerack24", clubid="1")])
    long_excerpt = ("도입부 " * 20) + "이번 글에서는 몬테스 알파를 소개한다 " + ("마무리 " * 20)
    item = CollectedItem(
        title="와인 추천", excerpt=long_excerpt, thumbnail_url="https://example.com/fresh.jpg",
        external_url="https://cafe.naver.com/winerack24/1", published_date=None, source_name="와쌉",
    )

    run_job(job.id, store, sources, "몬테스", "몬테스", **_news_deps(
        fetch_wassap_items=lambda source: [item],
        match_brands=lambda text, brands: ["몬테스"],
        get_existing_article=lambda url: {
            "title": "와인 추천", "excerpt": "도입부만 저장된 예전 요약", "thumbnail_url": None, "published_date": None,
        },
    ))

    result = store.get(job.id)
    assert result.results[0].status == "중복"
    assert "몬테스" in result.results[0].excerpt
    assert result.results[0].thumbnail_url == "https://example.com/fresh.jpg"


def test_run_job_international_source_failure_isolated_from_others():
    store = JobStore()
    job = store.create("몬테스", "몬테스", total=2)
    sources = _empty_sources(international=[
        InternationalSource(id="decanter", name="Decanter", url="https://decanter.com"),
        InternationalSource(id="oiv", name="OIV", url="https://oiv.int"),
    ])
    good_item = CollectedItem(
        title="몬테스 관련 소식", excerpt="", thumbnail_url=None,
        external_url="https://oiv.int/1", published_date=None, source_name="OIV",
    )

    def flaky_intl(source):
        if source.name == "Decanter":
            raise RuntimeError("파싱 실패")
        return [good_item]

    run_job(job.id, store, sources, "몬테스", "몬테스", **_news_deps(
        fetch_international_items=flaky_intl,
        match_brands=lambda text, brands: [],
    ))

    result = store.get(job.id)
    assert result.status == "partial"
    assert result.done == 4  # 해외소스 2개 + 블로그 검색 1 + 유튜브 검색 1(항상 켜짐)
    statuses = {r.source_name: r.status for r in result.results}
    assert statuses["Decanter"] == "실패"
    assert statuses["OIV"] == "저장됨"


def test_run_job_fails_immediately_when_brand_list_lookup_fails():
    store = JobStore()
    job = store.create("몬테스", "몬테스", total=1)
    sources = _empty_sources(news=[NewsSource(id="wine21.com", name="와인21", domain="wine21.com", query="와인21")])

    def broken_get_known_brands():
        raise RuntimeError("DB 연결 실패")

    run_job(job.id, store, sources, "몬테스", "몬테스", **_news_deps(get_known_brands=broken_get_known_brands))

    result = store.get(job.id)
    assert result.status == "failed"
    assert "DB 연결 실패" in result.error


def test_job_store_update_rejects_unknown_field():
    store = JobStore()
    job = store.create("몬테스", "몬테스", total=1)

    with pytest.raises(AttributeError):
        store.update(job.id, nonexistent_field="x")


def test_run_job_stops_early_when_deadline_already_passed():
    store = JobStore()
    job = store.create("몬테스", "몬테스", total=1)
    sources = _empty_sources(news=[NewsSource(id="wine21.com", name="와인21", domain="wine21.com", query="와인21")])

    run_job(job.id, store, sources, "몬테스", "몬테스", **_news_deps(
        fetch_naver_items=lambda query: [{"title": "a", "link": "https://wine21.com/1", "originallink": ""}],
        deadline=time.monotonic() - 1,
    ))

    result = store.get(job.id)
    assert result.status == "failed"
    assert "시간 제한" in result.error
    assert result.done == 0
