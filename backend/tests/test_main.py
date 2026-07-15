import app.main as main_module
from fastapi.testclient import TestClient


class ImmediateThread:
    """테스트에서는 백그라운드 스레드 대신 동기적으로 즉시 실행한다."""

    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}

    def start(self):
        self._target(*self._args, **self._kwargs)


def test_create_job_and_poll_status(monkeypatch):
    monkeypatch.setattr(main_module.threading, "Thread", ImmediateThread)

    def fake_run_job(job_id, store, sources, wine_name, brand, **deps):
        store.update(job_id, status="succeeded", done=len(sources))

    monkeypatch.setattr(main_module, "run_job", fake_run_job)

    client = TestClient(main_module.app)
    response = client.post(
        "/jobs",
        json={"wine_name": "몬테스 알파", "brand": "몬테스", "source_ids": ["wine21"]},
    )
    assert response.status_code == 200
    job_id = response.json()["job_id"]

    status_response = client.get(f"/jobs/{job_id}")
    assert status_response.status_code == 200
    body = status_response.json()
    assert body["status"] == "succeeded"
    assert body["done"] == 1


def test_create_job_rejects_empty_source_list(monkeypatch):
    monkeypatch.setattr(main_module.threading, "Thread", ImmediateThread)
    client = TestClient(main_module.app)
    response = client.post("/jobs", json={"wine_name": "몬테스", "brand": "", "source_ids": []})
    assert response.status_code == 400


def test_create_job_rejects_blank_wine_name(monkeypatch):
    monkeypatch.setattr(main_module.threading, "Thread", ImmediateThread)
    client = TestClient(main_module.app)
    response = client.post("/jobs", json={"wine_name": "  ", "brand": "", "source_ids": ["wine21"]})
    assert response.status_code == 400


def test_get_job_missing_returns_404():
    client = TestClient(main_module.app)
    response = client.get("/jobs/does-not-exist")
    assert response.status_code == 404


def test_create_job_ignores_invalid_source_ids(monkeypatch):
    monkeypatch.setattr(main_module.threading, "Thread", ImmediateThread)

    received_sources = []

    def fake_run_job(job_id, store, sources, wine_name, brand, **deps):
        received_sources.append(sources)
        store.update(job_id, status="succeeded", done=len(sources))

    monkeypatch.setattr(main_module, "run_job", fake_run_job)

    client = TestClient(main_module.app)
    response = client.post(
        "/jobs",
        json={
            "wine_name": "몬테스 알파",
            "brand": "몬테스",
            "source_ids": ["wine21", "not-a-real-source"],
        },
    )
    assert response.status_code == 200
    job_id = response.json()["job_id"]

    assert len(received_sources) == 1
    assert [s.id for s in received_sources[0]] == ["wine21"]

    status_response = client.get(f"/jobs/{job_id}")
    assert status_response.status_code == 200
    body = status_response.json()
    assert body["total"] == 1
    assert body["done"] == 1
