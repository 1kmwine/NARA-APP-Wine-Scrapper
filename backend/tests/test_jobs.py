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
        article_exists=lambda url: False,
        insert_article=lambda source_name, url, article, matched: 1,
        parse_article_meta=lambda html, fallback: _Article(),
        match_brands=lambda text, brands: ["몬테스"],
        extract_visible_text=lambda html: "본문",
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
    assert result.done == 1
    assert len(result.results) == 1
    assert result.results[0].status == "저장됨"
    assert result.results[0].source_category == "news"
    assert result.results[0].excerpt == "요약"


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
    assert result.done == 2
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
    assert result.done == 1
    assert result.results[0].source_category == "youtube"
    assert result.results[0].title == "몬테스 알파 리뷰"
    assert result.results[0].matched_brands == ["몬테스"]


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
        article_exists=lambda url: True,
        insert_article=lambda *a, **k: insert_calls.append(1) or 1,
    ))

    result = store.get(job.id)
    assert result.results[0].status == "중복"
    assert insert_calls == []


def test_run_job_international_source_failure_isolated_from_others():
    store = JobStore()
    job = store.create("몬테스", "몬테스", total=2)
    sources = _empty_sources(international=[
        InternationalSource(id="decanter", name="Decanter", url="https://decanter.com"),
        InternationalSource(id="oiv", name="OIV", url="https://oiv.int"),
    ])
    good_item = CollectedItem(
        title="OIV 소식", excerpt="", thumbnail_url=None,
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
    assert result.done == 2
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
