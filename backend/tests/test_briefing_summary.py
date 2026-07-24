import json

import pytest

from app import briefing_summary as bs


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(bs, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(bs, "SUMMARIES_DIR", tmp_path / "summaries")
    return tmp_path / "data"


def test_load_week_entries_by_category_merges_seven_days(data_dir):
    _write_json(data_dir / "2026-07-20" / "news.json", [{"title": "월요일 뉴스", "press": "소믈리에타임즈"}])
    _write_json(data_dir / "2026-07-21" / "news.json", [{"title": "화요일 뉴스"}, {"title": ""}])
    _write_json(data_dir / "2026-07-20" / "youtube.json", {"채널A": [{"title": "영상1"}], "채널B": []})
    _write_json(data_dir / "2026-07-20" / "international.json", {
        "foreign_magazines": [{"title_ko": "해외기사1", "source": "Decanter"}],
        "events": [{"title": "영문만 있는 이벤트"}],
    })

    result = bs.load_week_entries_by_category("2026-07-20")

    assert result["news"] == [
        {"title": "월요일 뉴스", "source": "소믈리에타임즈"},
        {"title": "화요일 뉴스", "source": ""},
    ]  # 빈 제목은 걸러짐
    assert result["youtube"] == [{"title": "영상1", "source": "채널A"}]
    assert result["international"] == [
        {"title": "해외기사1", "source": "Decanter"},
        {"title": "영문만 있는 이벤트", "source": ""},
    ]
    assert result["wassap"] == []  # 파일 자체가 없는 날/카테고리는 빈 리스트


def test_load_week_entries_skips_missing_day_directories(data_dir):
    _write_json(data_dir / "2026-07-20" / "news.json", [{"title": "뉴스"}])
    # 7/21~7/26은 디렉토리 자체가 없음 — 예외 없이 조용히 건너뛰어야 한다
    result = bs.load_week_entries_by_category("2026-07-20")
    assert result["news"] == [{"title": "뉴스", "source": ""}]


def test_bucket_entries_maps_categories_to_three_buckets():
    entries_by_category = {
        "news": [{"title": "뉴스1", "source": ""}], "newsroom": [{"title": "칼럼1", "source": ""}],
        "wassap": [{"title": "와쌉1", "source": ""}], "blog": [{"title": "블로그1", "source": ""}],
        "youtube": [{"title": "영상1", "source": ""}], "international": [{"title": "해외1", "source": ""}],
    }
    buckets = bs.bucket_entries(entries_by_category)
    assert buckets["global"] == [{"title": "해외1", "source": ""}]
    assert {e["title"] for e in buckets["consumer"]} == {"영상1", "와쌉1", "블로그1"}
    assert {e["title"] for e in buckets["importer"]} == {"뉴스1", "칼럼1"}


def test_compute_fingerprint_stable_for_same_counts_changes_when_counts_change():
    a = {"news": [{"title": "a"}, {"title": "b"}], "youtube": []}
    b = {"news": [{"title": "x"}, {"title": "y"}], "youtube": []}  # 내용은 다르지만 건수는 같음
    c = {"news": [{"title": "a"}], "youtube": []}

    assert bs.compute_fingerprint(a) == bs.compute_fingerprint(b)
    assert bs.compute_fingerprint(a) != bs.compute_fingerprint(c)


def test_build_prompt_includes_category_headers_source_tag_and_truncation_note():
    buckets = {
        "global": [{"title": "해외 기사", "source": "Decanter"}] * 45,  # MAX_ITEMS_PER_BUCKET(40) 초과
        "consumer": [{"title": "소비자 글", "source": ""}],
        "importer": [],  # 빈 버킷은 프롬프트에서 아예 빠짐
    }
    prompt = bs.build_prompt(buckets)
    assert "## 글로벌 동향" in prompt
    assert "전체 45건 중 최근 40건만 표시" in prompt
    assert "[Decanter]" in prompt
    assert "## 소비자 트렌드" in prompt
    assert "업계 활동" not in prompt


class _FakeGeminiResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FakeGeminiClient:
    def __init__(self, text):
        self._text = text
        self.last_call = None

    def post(self, url, *, params=None, json=None, timeout=None):
        self.last_call = {"url": url, "params": params, "json": json}
        return _FakeGeminiResponse({"candidates": [{"content": {"parts": [{"text": self._text}]}}]})


def test_call_gemini_parses_json_response_text():
    client = _FakeGeminiClient('{"global": ["키워드1"], "consumer": ["키워드2"], "importer": ["키워드3"]}')

    result = bs.call_gemini("프롬프트", "fake-key", client=client)

    assert result == {"global": ["키워드1"], "consumer": ["키워드2"], "importer": ["키워드3"]}
    assert client.last_call["params"]["key"] == "fake-key"
    assert client.last_call["json"]["generationConfig"]["responseMimeType"] == "application/json"


def test_build_weekly_summary_calls_llm_on_cache_miss(data_dir):
    _write_json(data_dir / "2026-07-20" / "news.json", [{"title": "뉴스1"}])
    client = _FakeGeminiClient('{"global": [], "consumer": [], "importer": ["업계 키워드1", "업계 키워드2"]}')

    result = bs.build_weekly_summary("2026-07-20", "fake-key", client=client)

    assert result["cached"] is False
    assert result["week_end"] == "2026-07-26"
    importer = next(c for c in result["categories"] if c["key"] == "importer")
    assert importer["keywords"] == ["업계 키워드1", "업계 키워드2"]
    assert importer["item_count"] == 1
    assert client.last_call is not None  # 실제로 LLM 호출됨


def test_build_weekly_summary_uses_cache_when_fingerprint_matches(data_dir):
    _write_json(data_dir / "2026-07-20" / "news.json", [{"title": "뉴스1"}])
    client = _FakeGeminiClient('{"global": [], "consumer": [], "importer": ["첫 생성"]}')
    first = bs.build_weekly_summary("2026-07-20", "fake-key", client=client)
    assert first["cached"] is False

    client2 = _FakeGeminiClient('{"global": [], "consumer": [], "importer": ["다시 생성되면 안 됨"]}')
    second = bs.build_weekly_summary("2026-07-20", "fake-key", client=client2)

    assert second["cached"] is True
    assert client2.last_call is None  # 캐시 히트라 LLM 호출 자체가 없어야 함
    importer = next(c for c in second["categories"] if c["key"] == "importer")
    assert importer["keywords"] == ["첫 생성"]


def test_build_weekly_summary_forces_empty_keywords_when_bucket_has_no_items(data_dir):
    # 실측(2026-07-24): international.json이 없는 주(global 버킷 0건)인데도
    # Gemini가 "global" 키에 다른 버킷 내용을 오분류해 채워서 응답한 적이
    # 있었다 — 원본 소스가 0건이면 LLM이 뭘 반환하든 무조건 빈 배열로 덮는다.
    _write_json(data_dir / "2026-07-20" / "news.json", [{"title": "뉴스1"}])
    client = _FakeGeminiClient(
        '{"global": ["엉뚱하게 채워진 키워드"], "consumer": [], "importer": ["업계 키워드"]}'
    )

    result = bs.build_weekly_summary("2026-07-20", "fake-key", client=client)

    global_cat = next(c for c in result["categories"] if c["key"] == "global")
    assert global_cat["item_count"] == 0
    assert global_cat["keywords"] == []


def test_build_weekly_summary_skips_llm_when_week_is_completely_empty(data_dir):
    client = _FakeGeminiClient("should not be called")

    result = bs.build_weekly_summary("2026-07-20", "fake-key", client=client)

    assert client.last_call is None
    assert all(c["keywords"] == [] for c in result["categories"])
