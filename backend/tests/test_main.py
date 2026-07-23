import app.main as main_module
from fastapi.testclient import TestClient
from app.sources import NewsSource, SourcesConfig


class ImmediateThread:
    """테스트에서는 백그라운드 스레드 대신 동기적으로 즉시 실행한다."""

    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}

    def start(self):
        self._target(*self._args, **self._kwargs)


def _one_news_source_config():
    return SourcesConfig(news=[NewsSource(id="wine21.com", name="와인21", domain="wine21.com", query="와인21")])


def test_create_job_and_poll_status(monkeypatch):
    monkeypatch.setattr(main_module.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(main_module, "_load_current_sources", lambda: _one_news_source_config())

    def fake_run_job(job_id, store, sources, wine_name, brand, **deps):
        store.update(job_id, status="succeeded", done=sources.total_count())

    monkeypatch.setattr(main_module, "run_job", fake_run_job)

    client = TestClient(main_module.app)
    response = client.post("/jobs", json={"wine_name": "몬테스 알파", "brand": "몬테스"})
    assert response.status_code == 200
    job_id = response.json()["job_id"]

    status_response = client.get(f"/jobs/{job_id}")
    assert status_response.status_code == 200
    body = status_response.json()
    assert body["status"] == "succeeded"
    assert body["done"] == 4  # 뉴스 소스 1개 + 블로그/유튜브검색/웹검색 각 1(항상 켜짐)
    assert body["total"] == 4
    assert body["results"] == []
    assert body["failures"] == []


def test_create_job_rejects_blank_wine_name(monkeypatch):
    monkeypatch.setattr(main_module.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(main_module, "_load_current_sources", lambda: _one_news_source_config())
    client = TestClient(main_module.app)
    response = client.post("/jobs", json={"wine_name": "  ", "brand": ""})
    assert response.status_code == 400


def test_create_job_allows_blog_only_when_no_other_sources_configured(monkeypatch):
    # 블로그 검색은 등록 소스 목록이 없는 항상-켜짐 카테고리라, 다른 소스가 전부
    # 비어 있어도 total_count()가 0이 아니게 됐다 — "설정된 소스가 없습니다" 거부는
    # 더 이상 트리거되지 않는다(블로그만으로도 작업이 의미가 있으므로 의도된 변화).
    monkeypatch.setattr(main_module.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(main_module, "_load_current_sources", lambda: SourcesConfig())

    def fake_run_job(job_id, store, sources, wine_name, brand, **deps):
        store.update(job_id, status="succeeded", done=sources.total_count())

    monkeypatch.setattr(main_module, "run_job", fake_run_job)
    client = TestClient(main_module.app)
    response = client.post("/jobs", json={"wine_name": "몬테스", "brand": ""})
    assert response.status_code == 200


def test_get_job_missing_returns_404():
    client = TestClient(main_module.app)
    response = client.get("/jobs/does-not-exist")
    assert response.status_code == 404


def test_get_job_splits_results_and_failures(monkeypatch):
    monkeypatch.setattr(main_module.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(main_module, "_load_current_sources", lambda: _one_news_source_config())

    from app.jobs import JobResultItem

    def fake_run_job(job_id, store, sources, wine_name, brand, **deps):
        store.append_result(job_id, JobResultItem(
            source_id="wine21.com", source_name="와인21", source_category="news",
            title="몬테스 기사", published_date="2026-07-01", external_url="https://wine21.com/1",
            excerpt="요약", thumbnail_url="https://x/1.jpg", status="저장됨", matched_brands=["몬테스"],
        ))
        store.append_result(job_id, JobResultItem(
            source_id="wine21.com", source_name="와인21", source_category="news",
            title="", published_date=None, external_url="https://wine21.com/2", status="실패",
            reason="og:meta 파싱 실패",
        ))
        store.update(job_id, status="partial", done=1)

    monkeypatch.setattr(main_module, "run_job", fake_run_job)

    client = TestClient(main_module.app)
    response = client.post("/jobs", json={"wine_name": "몬테스", "brand": ""})
    job_id = response.json()["job_id"]

    body = client.get(f"/jobs/{job_id}").json()
    assert len(body["results"]) == 1
    assert body["results"][0]["title"] == "몬테스 기사"
    assert body["results"][0]["excerpt"] == "요약"
    assert body["results"][0]["source_category"] == "news"
    assert len(body["failures"]) == 1
    assert body["failures"][0]["reason"] == "og:meta 파싱 실패"
    assert "title" not in body["failures"][0]


def test_add_news_source_success(monkeypatch):
    calls = {}

    def fake_add_news_source(client, token, **kwargs):
        calls.update(kwargs)

    monkeypatch.setattr(main_module.source_config, "add_news_source", fake_add_news_source)

    client = TestClient(main_module.app)
    response = client.post("/sources", json={
        "category": "news", "press": "한국경제", "news_category": "뉴스",
        "query": "한국경제 와인", "url": "https://www.hankyung.com/",
    })
    assert response.status_code == 200
    assert calls["press"] == "한국경제"


def test_add_source_missing_required_fields_returns_400():
    client = TestClient(main_module.app)
    response = client.post("/sources", json={"category": "news", "press": "", "query": "", "url": ""})
    assert response.status_code == 400


def test_add_source_duplicate_returns_409(monkeypatch):
    from app.source_config import DuplicateSourceError

    def fake_add_news_source(client, token, **kwargs):
        raise DuplicateSourceError("이미 등록됨")

    monkeypatch.setattr(main_module.source_config, "add_news_source", fake_add_news_source)

    client = TestClient(main_module.app)
    response = client.post("/sources", json={
        "category": "news", "press": "와인21", "news_category": "매거진",
        "query": "와인21", "url": "https://www.wine21.com/",
    })
    assert response.status_code == 409


def test_add_source_unknown_category_returns_400():
    client = TestClient(main_module.app)
    response = client.post("/sources", json={"category": "unknown"})
    assert response.status_code == 400


def test_get_sources_returns_counts_and_names(monkeypatch):
    monkeypatch.setattr(main_module, "_load_current_sources", lambda: SourcesConfig(
        news=[NewsSource(id="wine21.com", name="와인21", domain="wine21.com", query="와인21")],
        youtube=[], wassap=[], international=[],
    ))
    client = TestClient(main_module.app)
    response = client.get("/sources")
    assert response.status_code == 200
    body = response.json()
    assert body["counts"] == {"news": 1, "youtube": 1, "wassap": 0, "international": 1, "blog": 1}
    assert body["names"]["news"] == ["와인21"]
    assert body["names"]["youtube"] == []


def test_get_sources_returns_502_on_load_failure(monkeypatch):
    def broken():
        raise RuntimeError("github down")

    monkeypatch.setattr(main_module, "_load_current_sources", broken)
    client = TestClient(main_module.app)
    response = client.get("/sources")
    assert response.status_code == 502
