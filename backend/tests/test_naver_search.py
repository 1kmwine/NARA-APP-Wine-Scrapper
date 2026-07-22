from app.naver_search import (
    naver_search, fetch_all_items, items_for_domain, search_blog, NAVER_NEWS_URL, NAVER_BLOG_URL,
)


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class FakeClient:
    def __init__(self, payload):
        self._payload = payload
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, params, headers))
        return FakeResponse(self._payload)


class MultiFakeClient:
    def __init__(self, responses_by_url):
        self._responses = responses_by_url
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, params, headers))
        return FakeResponse(self._responses[url])


class RetryThenSucceedClient:
    """첫 호출은 429, 두 번째 호출은 성공하는 스텁."""

    def __init__(self, payload):
        self._payload = payload
        self.calls = 0

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls += 1
        if self.calls == 1:
            return FakeResponse({}, status_code=429)
        return FakeResponse(self._payload)


class AlwaysRateLimitedClient:
    def __init__(self):
        self.calls = 0

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls += 1
        return FakeResponse({}, status_code=429)


def test_naver_search_strips_bold_tags_from_title():
    client = FakeClient({"items": [{"title": "<b>몬테스</b> 알파 신제품", "link": "https://wine21.com/1", "originallink": ""}]})
    result = naver_search("몬테스", NAVER_NEWS_URL, "id", "secret", client)
    assert result == [{"title": "몬테스 알파 신제품", "link": "https://wine21.com/1", "originallink": ""}]


def test_naver_search_unescapes_html_entities_in_title():
    client = FakeClient({"items": [{"title": "&quot;로저 구라트&quot; 신제품", "link": "https://wine21.com/1", "originallink": ""}]})
    result = naver_search("로저구라트", NAVER_NEWS_URL, "id", "secret", client)
    assert result[0]["title"] == '"로저 구라트" 신제품'


def test_naver_search_sends_client_credentials_header():
    client = FakeClient({"items": []})
    naver_search("몬테스", NAVER_NEWS_URL, "my-id", "my-secret", client)
    _, _, headers = client.calls[0]
    assert headers["X-Naver-Client-Id"] == "my-id"
    assert headers["X-Naver-Client-Secret"] == "my-secret"


def test_naver_search_retries_once_on_429_then_succeeds():
    client = RetryThenSucceedClient({"items": [{"title": "a", "link": "https://x.com/1", "originallink": ""}]})
    result = naver_search("몬테스", NAVER_NEWS_URL, "id", "secret", client, retry_delay_seconds=0)
    assert client.calls == 2
    assert len(result) == 1


def test_naver_search_gives_up_after_max_retries():
    client = AlwaysRateLimitedClient()
    import pytest
    with pytest.raises(RuntimeError):
        naver_search("몬테스", NAVER_NEWS_URL, "id", "secret", client, retry_delay_seconds=0)
    assert client.calls == 3  # 최초 1회 + 재시도 2회


def test_fetch_all_items_calls_news_and_blog_exactly_once_each():
    client = MultiFakeClient({
        NAVER_NEWS_URL: {"items": [{"title": "a", "link": "https://wine21.com/1", "originallink": ""}]},
        NAVER_BLOG_URL: {"items": [{"title": "b", "link": "https://wine21.com/2", "originallink": ""}]},
    })
    items = fetch_all_items("몬테스", "id", "secret", client, call_interval_seconds=0)
    news_calls = [c for c in client.calls if c[0] == NAVER_NEWS_URL]
    blog_calls = [c for c in client.calls if c[0] == NAVER_BLOG_URL]
    assert len(news_calls) == 1
    assert len(blog_calls) == 1
    assert len(items) == 2


def test_search_blog_extracts_description_postdate_and_bloggername():
    client = FakeClient({"items": [{
        "title": "<b>로저 구라트</b> 데미세크",
        "description": "<b>로저 구라트</b> 카바 시음기...",
        "link": "https://blog.naver.com/naracellar/224352889386",
        "bloggername": "나라셀라",
        "postdate": "20260721",
    }]})
    result = search_blog("로저구라트", "id", "secret", client)
    assert result == [{
        "title": "로저 구라트 데미세크",
        "description": "로저 구라트 카바 시음기...",
        "link": "https://blog.naver.com/naracellar/224352889386",
        "bloggername": "나라셀라",
        "postdate": "20260721",
    }]


def test_items_for_domain_prefers_originallink_over_rewritten_link():
    items = [{"title": "a", "link": "https://n.news.naver.com/1", "originallink": "https://hankyung.com/1"}]
    urls = items_for_domain(items, "hankyung.com")
    assert urls == ["https://hankyung.com/1"]


def test_items_for_domain_falls_back_to_link_when_no_originallink_match():
    items = [{"title": "a", "link": "https://wine21.com/3", "originallink": ""}]
    urls = items_for_domain(items, "wine21.com")
    assert urls == ["https://wine21.com/3"]


def test_items_for_domain_filters_out_non_matching_and_dedupes():
    items = [
        {"title": "a", "link": "https://wine21.com/1", "originallink": ""},
        {"title": "b", "link": "https://other.com/2", "originallink": ""},
        {"title": "c", "link": "https://wine21.com/1", "originallink": ""},
    ]
    urls = items_for_domain(items, "wine21.com")
    assert urls == ["https://wine21.com/1"]


def test_items_for_domain_no_network_calls():
    """순수 함수 — 클라이언트를 아예 받지 않으므로 네트워크 호출 자체가 불가능함을 시그니처로 보장."""
    import inspect
    params = inspect.signature(items_for_domain).parameters
    assert "client" not in params
