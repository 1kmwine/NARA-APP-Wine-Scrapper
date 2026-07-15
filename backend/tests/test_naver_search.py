from app.naver_search import naver_search, search_urls_for_domain, NAVER_NEWS_URL, NAVER_BLOG_URL


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

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
    """news/blog 두 엔드포인트에 각각 다른 응답을 주기 위한 스텁"""

    def __init__(self, responses_by_url):
        self._responses = responses_by_url
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, params, headers))
        return FakeResponse(self._responses[url])


def test_naver_search_strips_bold_tags_from_title():
    client = FakeClient({"items": [{"title": "<b>몬테스</b> 알파 신제품", "link": "https://wine21.com/1"}]})
    result = naver_search("몬테스", NAVER_NEWS_URL, "id", "secret", client)
    assert result == [{"title": "몬테스 알파 신제품", "link": "https://wine21.com/1"}]


def test_naver_search_sends_client_credentials_header():
    client = FakeClient({"items": []})
    naver_search("몬테스", NAVER_NEWS_URL, "my-id", "my-secret", client)
    _, _, headers = client.calls[0]
    assert headers["X-Naver-Client-Id"] == "my-id"
    assert headers["X-Naver-Client-Secret"] == "my-secret"


def test_search_urls_for_domain_filters_and_dedupes():
    client = MultiFakeClient({
        NAVER_NEWS_URL: {"items": [
            {"title": "a", "link": "https://wine21.com/1"},
            {"title": "b", "link": "https://other.com/2"},
        ]},
        NAVER_BLOG_URL: {"items": [
            {"title": "c", "link": "https://wine21.com/1"},  # 중복 URL
            {"title": "d", "link": "https://wine21.com/3"},
        ]},
    })
    urls = search_urls_for_domain("몬테스", "wine21.com", "id", "secret", client)
    assert urls == ["https://wine21.com/1", "https://wine21.com/3"]
