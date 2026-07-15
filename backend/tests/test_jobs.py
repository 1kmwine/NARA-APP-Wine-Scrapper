import time

import pytest

from app.jobs import JobStore, run_job
from app.sources import Source


class _Article:
    def __init__(self):
        self.title = "제목"
        self.excerpt = "요약"
        self.thumbnail_url = None
        self.published_date = "2026-07-01"


def test_run_job_succeeds_when_all_sources_ok():
    store = JobStore()
    job = store.create("몬테스", "몬테스", total=1)
    sources = [Source("wine21", "와인21", "wine21.com")]

    run_job(
        job.id, store, sources, "몬테스", "몬테스",
        search_urls_for_domain=lambda q, d: ["https://wine21.com/1"],
        fetch_html=lambda url: "<html></html>",
        get_known_brands=lambda: ["몬테스"],
        article_exists=lambda url: False,
        insert_article=lambda source_name, url, article, matched: 1,
        parse_article_meta=lambda html, fallback: _Article(),
        match_brands=lambda text, brands: ["몬테스"],
        extract_visible_text=lambda html: "본문",
    )

    result = store.get(job.id)
    assert result.status == "succeeded"
    assert result.done == 1
    assert len(result.results) == 1
    assert result.results[0].status == "저장됨"
    assert result.results[0].matched_brands == ["몬테스"]


def test_run_job_marks_partial_when_a_source_search_fails():
    store = JobStore()
    job = store.create("몬테스", "몬테스", total=2)
    sources = [
        Source("wine21", "와인21", "wine21.com"),
        Source("winein", "와인인", "winein.co.kr"),
    ]

    def flaky_search(query, domain):
        if domain == "winein.co.kr":
            raise RuntimeError("naver api 오류")
        return []

    run_job(
        job.id, store, sources, "몬테스", "몬테스",
        search_urls_for_domain=flaky_search,
        fetch_html=lambda url: "<html></html>",
        get_known_brands=lambda: [],
        article_exists=lambda url: False,
        insert_article=lambda *a, **k: 1,
        parse_article_meta=lambda html, fallback: _Article(),
        match_brands=lambda text, brands: [],
        extract_visible_text=lambda html: "",
    )

    result = store.get(job.id)
    assert result.status == "partial"
    assert result.done == 2


def test_run_job_marks_duplicate_results_without_reinserting():
    store = JobStore()
    job = store.create("몬테스", "몬테스", total=1)
    sources = [Source("wine21", "와인21", "wine21.com")]
    insert_calls = []

    run_job(
        job.id, store, sources, "몬테스", "몬테스",
        search_urls_for_domain=lambda q, d: ["https://wine21.com/1"],
        fetch_html=lambda url: "<html></html>",
        get_known_brands=lambda: [],
        article_exists=lambda url: True,
        insert_article=lambda *a, **k: insert_calls.append(1) or 1,
        parse_article_meta=lambda html, fallback: _Article(),
        match_brands=lambda text, brands: [],
        extract_visible_text=lambda html: "",
    )

    result = store.get(job.id)
    assert result.results[0].status == "중복"
    assert insert_calls == []


def test_run_job_fails_immediately_when_brand_list_lookup_fails():
    store = JobStore()
    job = store.create("몬테스", "몬테스", total=1)
    sources = [Source("wine21", "와인21", "wine21.com")]

    def broken_get_known_brands():
        raise RuntimeError("DB 연결 실패")

    run_job(
        job.id, store, sources, "몬테스", "몬테스",
        search_urls_for_domain=lambda q, d: [],
        fetch_html=lambda url: "",
        get_known_brands=broken_get_known_brands,
        article_exists=lambda url: False,
        insert_article=lambda *a, **k: 1,
        parse_article_meta=lambda html, fallback: _Article(),
        match_brands=lambda text, brands: [],
        extract_visible_text=lambda html: "",
    )

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
    job = store.create("몬테스", "몬테스", total=2)
    sources = [
        Source("wine21", "와인21", "wine21.com"),
        Source("winein", "와인인", "winein.co.kr"),
    ]

    run_job(
        job.id, store, sources, "몬테스", "몬테스",
        search_urls_for_domain=lambda q, d: ["https://example.com/1"],
        fetch_html=lambda url: "<html></html>",
        get_known_brands=lambda: ["몬테스"],
        article_exists=lambda url: False,
        insert_article=lambda source_name, url, article, matched: 1,
        parse_article_meta=lambda html, fallback: _Article(),
        match_brands=lambda text, brands: ["몬테스"],
        extract_visible_text=lambda html: "본문",
        deadline=time.monotonic() - 1,
    )

    result = store.get(job.id)
    assert result.status == "failed"
    assert "시간 제한" in result.error
    assert result.done == 0
    assert result.results == []


def test_run_job_with_generous_deadline_matches_no_deadline_behavior():
    store = JobStore()
    job = store.create("몬테스", "몬테스", total=1)
    sources = [Source("wine21", "와인21", "wine21.com")]

    run_job(
        job.id, store, sources, "몬테스", "몬테스",
        search_urls_for_domain=lambda q, d: ["https://wine21.com/1"],
        fetch_html=lambda url: "<html></html>",
        get_known_brands=lambda: ["몬테스"],
        article_exists=lambda url: False,
        insert_article=lambda source_name, url, article, matched: 1,
        parse_article_meta=lambda html, fallback: _Article(),
        match_brands=lambda text, brands: ["몬테스"],
        extract_visible_text=lambda html: "본문",
        deadline=time.monotonic() + 60,
    )

    result = store.get(job.id)
    assert result.status == "succeeded"
    assert result.done == 1
    assert len(result.results) == 1
    assert result.results[0].status == "저장됨"
    assert result.results[0].matched_brands == ["몬테스"]
