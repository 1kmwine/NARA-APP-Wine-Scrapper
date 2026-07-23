import json
from datetime import date, timedelta

from app.collectors import CollectedItem, collect_youtube
from app.sources import YoutubeSource


class FakeYoutubeResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


class FakeYoutubeClient:
    def __init__(self, pages: dict[str, str]):
        self._pages = pages

    def get(self, url, timeout=None):
        for prefix, text in self._pages.items():
            if url.startswith(prefix):
                return FakeYoutubeResponse(text)
        raise AssertionError(f"예상치 못한 URL: {url}")


def _channel_page(video_id, title, date_text, thumbnail_url="https://i.ytimg.com/vi/abc123/hqdefault.jpg"):
    data = {
        "contents": {"twoColumnBrowseResultsRenderer": {"tabs": [
            {},
            {"tabRenderer": {"content": {"richGridRenderer": {"contents": [
                {"richItemRenderer": {"content": {"videoRenderer": {
                    "videoId": video_id,
                    "title": {"runs": [{"text": title}]},
                    "publishedTimeText": {"simpleText": date_text},
                    "thumbnail": {"thumbnails": [{"url": thumbnail_url, "width": 360, "height": 202}]},
                }}}}
            ]}}}},
        ]}}
    }
    return f"<html><script>var ytInitialData = {json.dumps(data)};</script></html>"


def test_collect_youtube_with_known_channel_id():
    source = YoutubeSource(id="bimirya", name="비밀이야", handle="bimirya", channel_id="UCaKQ7_GT0k8u_sL0nE2tgkA")
    html = _channel_page("abc123", "몬테스 알파 시음", "1일 전")
    client = FakeYoutubeClient({"https://www.youtube.com/channel/UCaKQ7_GT0k8u_sL0nE2tgkA": html})

    items = collect_youtube(source, client, max_age_days=7)

    assert len(items) == 1
    assert items[0].title == "몬테스 알파 시음"
    assert items[0].external_url == "https://youtu.be/abc123"
    assert items[0].source_name == "YouTube: 비밀이야"
    assert items[0].published_date == (date.today() - timedelta(days=1)).isoformat()
    assert items[0].thumbnail_url == "https://i.ytimg.com/vi/abc123/hqdefault.jpg"


def test_collect_youtube_resolves_channel_id_when_blank():
    source = YoutubeSource(id="newchannel", name="신규채널", handle="newchannel", channel_id="")
    handle_html = '<html>"channelId":"UCresolved00000000000000"</html>'
    channel_html = _channel_page("v1", "새 영상", "3일 전")
    client = FakeYoutubeClient({
        "https://www.youtube.com/@newchannel": handle_html,
        "https://www.youtube.com/channel/UCresolved00000000000000": channel_html,
    })

    items = collect_youtube(source, client, max_age_days=7)

    assert len(items) == 1
    assert items[0].external_url == "https://youtu.be/v1"


def test_collect_youtube_returns_empty_when_channel_id_unresolvable():
    source = YoutubeSource(id="ghost", name="유령채널", handle="ghost", channel_id="")
    client = FakeYoutubeClient({"https://www.youtube.com/@ghost": "<html>no channel id here</html>"})

    items = collect_youtube(source, client, max_age_days=7)

    assert items == []


def test_collect_youtube_filters_out_videos_older_than_max_age():
    source = YoutubeSource(id="bimirya", name="비밀이야", handle="bimirya", channel_id="UCaKQ7_GT0k8u_sL0nE2tgkA")
    html = _channel_page("old1", "오래된 영상", "30일 전")
    client = FakeYoutubeClient({"https://www.youtube.com/channel/UCaKQ7_GT0k8u_sL0nE2tgkA": html})

    items = collect_youtube(source, client, max_age_days=7)

    assert items == []


from app.collectors import collect_youtube_search


class FakeYoutubeSearchClient:
    def __init__(self, html):
        self._html = html

    def get(self, url, params=None, headers=None, timeout=None):
        return FakeYoutubeResponse(self._html)


def _search_results_page(*videos):
    """videos: (video_id, title, date_text, channel_name, thumbnail_url) 튜플들."""
    content_items = []
    for video_id, title, date_text, channel, thumbnail_url in videos:
        content_items.append({"videoRenderer": {
            "videoId": video_id,
            "title": {"runs": [{"text": title}]},
            "publishedTimeText": {"simpleText": date_text},
            "longBylineText": {"runs": [{"text": channel}]},
            "thumbnail": {"thumbnails": [{"url": thumbnail_url, "width": 360, "height": 202}]},
        }})
    # 채널 렌더러 같은 비디오 아님 항목도 섞여 있는 게 실제 상황 — 걸러지는지 같이 검증
    content_items.insert(1 if len(content_items) > 1 else 0, {"channelRenderer": {"channelId": "UCxxx"}})
    data = {"contents": {"twoColumnSearchResultsRenderer": {"primaryContents": {"sectionListRenderer": {"contents": [
        {"itemSectionRenderer": {"contents": content_items}},
    ]}}}}}
    return f"<html><script>var ytInitialData = {json.dumps(data)};</script></html>"


def test_collect_youtube_search_returns_videos_skipping_non_video_items():
    html = _search_results_page(
        ("v1", "로저구라트 까바 리뷰", "2일 전", "와인 마시는 아톰", "https://i.ytimg.com/vi/v1/hqdefault.jpg"),
    )
    client = FakeYoutubeSearchClient(html)

    items = collect_youtube_search("로저구라트", client)

    assert len(items) == 1
    assert items[0].title == "로저구라트 까바 리뷰"
    assert items[0].external_url == "https://youtu.be/v1"
    assert items[0].source_name == "YouTube: 와인 마시는 아톰"
    assert items[0].thumbnail_url == "https://i.ytimg.com/vi/v1/hqdefault.jpg"


def test_collect_youtube_search_caps_at_max_items():
    html = _search_results_page(*[
        (f"v{i}", f"영상{i}", "1일 전", "채널", "https://i.ytimg.com/vi/x/hqdefault.jpg")
        for i in range(20)
    ])
    client = FakeYoutubeSearchClient(html)

    items = collect_youtube_search("로저구라트", client, max_items=12)

    assert len(items) == 12


def test_collect_youtube_search_returns_empty_when_no_ytinitialdata():
    client = FakeYoutubeSearchClient("<html>no data here</html>")
    assert collect_youtube_search("로저구라트", client) == []


def test_collected_item_title_truncated_to_500_chars():
    source = YoutubeSource(id="bimirya", name="비밀이야", handle="bimirya", channel_id="UCaKQ7_GT0k8u_sL0nE2tgkA")
    html = _channel_page("v1", "가" * 600, "1시간 전")
    client = FakeYoutubeClient({"https://www.youtube.com/channel/UCaKQ7_GT0k8u_sL0nE2tgkA": html})

    items = collect_youtube(source, client, max_age_days=7)

    assert len(items[0].title) == 500


from app.collectors import collect_wassap
from app.sources import WassapSource


class FakeWassapResponse:
    def __init__(self, content: bytes, text: str = ""):
        self.content = content
        self.text = text

    def raise_for_status(self):
        pass


class FakeWassapClient:
    def __init__(self, list_html: str, search_html_by_keyword: dict[str, str] | None = None):
        self._list_html = list_html
        self._search_html = search_html_by_keyword or {}

    def get(self, url, *, params=None, headers=None, timeout=None):
        if "cafe.naver.com/winerack24" in url and params is None:
            return FakeWassapResponse(self._list_html.encode("euc-kr"))
        if "search.naver.com" in url:
            keyword = params["query"]
            return FakeWassapResponse(b"", text=self._search_html.get(keyword, ""))
        raise AssertionError(f"예상치 못한 요청: {url} {params}")


LIST_HTML = (
    '<a href="/ArticleRead.nhn?clubid=10050146&amp;articleid=365033" '
    'title="답0/댓5"><div class="ellipsis tcol-c">몬테스 알파 재입고 문의</div></a>'
    '<a href="/ArticleRead.nhn?clubid=10050146&amp;articleid=365034" '
    'title="답0/댓2"><div class="ellipsis tcol-c">[공지] 카페 이용 규칙</div></a>'
)


def test_collect_wassap_parses_list_and_excludes_notices():
    source = WassapSource(id="winerack24-10050146", name="와쌉", cafe_id="winerack24", clubid="10050146")
    client = FakeWassapClient(LIST_HTML)

    items = collect_wassap(source, client, naver_cookie="fake-cookie")

    assert len(items) == 1
    assert items[0].title == "몬테스 알파 재입고 문의"
    assert items[0].external_url == "https://cafe.naver.com/winerack24/365033"
    assert items[0].source_name == "와쌉"


def test_collect_wassap_sorts_by_recency_not_comment_count():
    # 댓글 수가 아니라 article id(최신순)로 정렬돼야 한다 — 인기글에 밀려
    # 최신 관련 글이 빠지는 걸 막기 위해 2026-07-21에 정렬 기준을 바꿨다.
    html = (
        '<a href="/ArticleRead.nhn?clubid=10050146&amp;articleid=1" title="답0/댓20">'
        '<div class="ellipsis tcol-c">오래됐지만 댓글많음</div></a>'
        '<a href="/ArticleRead.nhn?clubid=10050146&amp;articleid=2" title="답0/댓1">'
        '<div class="ellipsis tcol-c">최신이지만 댓글적음</div></a>'
    )
    source = WassapSource(id="winerack24-10050146", name="와쌉", cafe_id="winerack24", clubid="10050146")
    client = FakeWassapClient(html)

    items = collect_wassap(source, client, naver_cookie="fake-cookie")

    assert items[0].title == "최신이지만 댓글적음"
    assert items[1].title == "오래됐지만 댓글많음"


def test_collect_wassap_limits_to_ten_items():
    rows = "".join(
        f'<a href="/ArticleRead.nhn?clubid=10050146&amp;articleid={i}" title="답0/댓{i}">'
        f'<div class="ellipsis tcol-c">글{i}</div></a>'
        for i in range(15)
    )
    source = WassapSource(id="winerack24-10050146", name="와쌉", cafe_id="winerack24", clubid="10050146")
    client = FakeWassapClient(rows)

    items = collect_wassap(source, client, naver_cookie="fake-cookie")

    assert len(items) == 10


from app.collectors import search_wassap


class FakeWassapApiResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class FakeWassapApiClient:
    def __init__(self, payload):
        self._payload = payload
        self.last_call = None

    def get(self, url, *, params=None, headers=None, timeout=None):
        assert "apis.cafe.naver.com/search/v2/cafes/20564405/search/articles" in url
        assert headers["X-Cafe-Product"] == "pc"
        self.last_call = {"url": url, "params": params}
        return FakeWassapApiResponse(self._payload)


WASSAP_API_PAYLOAD = {
    "result": {
        "articleList": [
            {
                "type": "ARTICLE",
                "item": {
                    "articleId": 111,
                    "subject": "<mark>디코이</mark> 후기",
                    "summary": "<b>디코이</b> 마셔봤는데 진짜 좋았어요",
                    "thumbnailImageUrl": "https://cafeptthumb-phinf.pstatic.net/x.jpg",
                    "addDate": "2026-07-21T10:00:00.000",
                },
            },
            {"type": "NOTICE", "item": {"subject": "공지"}},
        ]
    }
}


def test_search_wassap_uses_real_search_api():
    # 신형 카페(SPA)는 ArticleList.nhn/검색 둘 다 서버렌더링 안 됨(2026-07-22 확인) —
    # 그 SPA가 실제로 부르는 내부 검색 API를 그대로 쓴다. NOTICE 타입은 걸러낸다.
    source = WassapSource(
        id="winerack24-10050146", name="와쌉", cafe_id="winerack24", clubid="10050146",
        cafe_numeric_id="20564405",
    )
    client = FakeWassapApiClient(WASSAP_API_PAYLOAD)

    items = search_wassap("디코이", source, client, naver_cookie="fake-cookie")

    assert len(items) == 1
    assert items[0].title == "디코이 후기"
    assert items[0].excerpt == "디코이 마셔봤는데 진짜 좋았어요"
    assert items[0].external_url == "https://cafe.naver.com/winerack24/111"
    assert items[0].thumbnail_url == "https://cafeptthumb-phinf.pstatic.net/x.jpg"
    assert items[0].published_date == "2026-07-21"
    assert client.last_call["params"]["query"] == "디코이"


def test_search_wassap_skips_when_no_cafe_numeric_id():
    source = WassapSource(id="winerack24-10050146", name="와쌉", cafe_id="winerack24", clubid="10050146")
    client = FakeWassapApiClient(WASSAP_API_PAYLOAD)

    items = search_wassap("디코이", source, client, naver_cookie="fake-cookie")

    assert items == []


from app.collectors import collect_international
from app.sources import InternationalSource


class FakeInternationalResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


class FakeInternationalClient:
    def __init__(self, pages: dict[str, str]):
        self._pages = pages

    def get(self, url, timeout=None):
        return FakeInternationalResponse(self._pages[url])


def _identity_translate(text: str) -> str:
    return f"[번역]{text}"


DECANTER_HTML = (
    '<div class="listing__title">   와인 뉴스 제목 하나   </div>'
    '<div class="listing__text listing__text--synopsis">   부제 요약   </div>'
)


def test_collect_international_decanter():
    source = InternationalSource(id="decanter", name="Decanter", url="https://www.decanter.com/wine-news/")
    client = FakeInternationalClient({"https://www.decanter.com/wine-news/": DECANTER_HTML})

    items = collect_international(source, client, translate=_identity_translate)

    assert len(items) == 1
    assert items[0].title == "[번역]와인 뉴스 제목 하나"
    assert items[0].excerpt == "[번역]부제 요약"
    assert items[0].source_name == "Decanter"
    assert items[0].external_url == "https://www.decanter.com/wine-news/"


WINESPECTATOR_HTML = (
    '<a href="https://www.winespectator.com/articles/some-article">부르고뉴 와인 기사 제목입니다</a>'
    '<a href="https://www.winespectator.com/articles/some-article">기사 부제 요약입니다</a>'
)


def test_collect_international_wine_spectator():
    source = InternationalSource(id="wine-spectator", name="Wine Spectator", url="https://www.winespectator.com/")
    client = FakeInternationalClient({"https://www.winespectator.com/": WINESPECTATOR_HTML})

    items = collect_international(source, client, translate=_identity_translate)

    assert len(items) == 1
    assert items[0].title == "[번역]부르고뉴 와인 기사 제목입니다"
    assert items[0].external_url == "https://www.winespectator.com/articles/some-article"


OIV_HTML = '<a href="/press/oiv-report-2026">OIV 연례 보고서 발표</a>'


def test_collect_international_oiv():
    source = InternationalSource(id="oiv", name="OIV", url="https://www.oiv.int/news/press")
    client = FakeInternationalClient({"https://www.oiv.int/news/press": OIV_HTML})

    items = collect_international(source, client, translate=_identity_translate)

    assert len(items) == 1
    assert items[0].title == "[번역]OIV 연례 보고서 발표"
    assert items[0].external_url == "https://www.oiv.int/press/oiv-report-2026"


class FakeWSSearchClient:
    def __init__(self, search_html):
        self._search_html = search_html

    def get(self, url, *, params=None, timeout=None):
        assert url == "https://www.winespectator.com/search"
        assert params == {"q": "Opus One"}
        return FakeInternationalResponse(self._search_html)


WS_SEARCH_HTML = (
    '<h2 class="site-search__result-title">'
    '<a href="/wine/wine-detail/id/1/name/opus-one-2022">Opus One</a></h2>'
)


def test_collect_international_wine_spectator_searches_when_query_given():
    source = InternationalSource(id="wine-spectator", name="Wine Spectator", url="https://www.winespectator.com/")
    client = FakeWSSearchClient(WS_SEARCH_HTML)

    items = collect_international(
        source, client, translate=_identity_translate, query="오퍼스원",
        translate_query=lambda q: "Opus One",
    )

    assert len(items) == 1
    assert items[0].title == "[번역]Opus One"
    assert items[0].external_url == "https://www.winespectator.com/wine/wine-detail/id/1/name/opus-one-2022"


class FakeOIVSearchClient:
    def __init__(self, filtered_html, unfiltered_html):
        self._filtered = filtered_html
        self._unfiltered = unfiltered_html

    def get(self, url, *, params=None, timeout=None):
        assert url == "https://www.oiv.int/news/press"
        if params:
            assert params == {"rendered_item": "congress"}
            return FakeInternationalResponse(self._filtered)
        return FakeInternationalResponse(self._unfiltered)


def test_collect_international_oiv_uses_rendered_item_filter_when_query_given():
    source = InternationalSource(id="oiv", name="OIV", url="https://www.oiv.int/news/press")
    client = FakeOIVSearchClient(
        filtered_html='<a href="/press/congress-2026">World Congress 2026</a>',
        unfiltered_html=OIV_HTML,
    )

    items = collect_international(
        source, client, translate=_identity_translate, query="총회",
        translate_query=lambda q: "congress",
    )

    assert len(items) == 1
    assert items[0].title == "[번역]World Congress 2026"


def test_collect_international_unsupported_source_raises():
    source = InternationalSource(id="jamessuckling", name="James Suckling", url="https://www.jamessuckling.com/")
    client = FakeInternationalClient({})
    import pytest
    with pytest.raises(NotImplementedError):
        collect_international(source, client, translate=_identity_translate)


from app.collectors import search_web


class FakeDdgResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


class FakeDdgClient:
    def __init__(self, html):
        self._html = html
        self.last_params = None

    def get(self, url, *, params=None, headers=None, timeout=None):
        assert url == "https://html.duckduckgo.com/html/"
        self.last_params = params
        return FakeDdgResponse(self._html)


DDG_HTML = (
    '<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fpage&amp;rut=x">'
    'Roger Goulart | Winery</a>'
    '<a class="result__snippet" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fpage&amp;rut=x">'
    'Discover Roger Goulart wines</a>'
)


def test_search_web_extracts_title_snippet_and_real_url():
    # Decanter/Wine Spectator/OIV 3곳만으론 커버리지가 좁아서(니치 브랜드는
    # 다 0건) DuckDuckGo로 와인 관련 웹 전체를 훑는다.
    client = FakeDdgClient(DDG_HTML)

    items = search_web("Roger Goulart", client, translate=_identity_translate)

    assert len(items) == 1
    assert items[0].title == "[번역]Roger Goulart | Winery"
    assert items[0].excerpt == "[번역]Discover Roger Goulart wines"
    assert items[0].external_url == "https://example.com/page"
    assert items[0].source_name == "example.com"
    assert client.last_params["q"] == "Roger Goulart wine"


def test_default_translate_to_en_skips_already_english_text():
    from app.collectors import default_translate_to_en
    # DB(integrated_item_info)에서 이미 정확한 영문 표기를 찾은 경우 여기서 또
    # 번역기를 태우면 표기가 깨질 위험이 있다 — ASCII면 그냥 통과시킨다.
    assert default_translate_to_en("Caymus Cabernet Sauvignon") == "Caymus Cabernet Sauvignon"


from app.collectors import collect_naver_blog


class FakeBlogResponse:
    def __init__(self, payload=None, text=""):
        self._payload = payload
        self.text = text

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class FakeBlogClient:
    """검색 API(openapi.naver.com)와 썸네일용 PostView.naver 요청을 URL로 구분한다."""
    def __init__(self, payload, thumbnail_html_by_lognum=None):
        self._payload = payload
        self._thumbnails = thumbnail_html_by_lognum or {}

    def get(self, url, params=None, headers=None, timeout=None):
        if "openapi.naver.com" in url:
            return FakeBlogResponse(payload=self._payload)
        log_no = (params or {}).get("logNo", "")
        return FakeBlogResponse(text=self._thumbnails.get(log_no, "<html></html>"))


def test_collect_naver_blog_builds_items_from_search_api():
    client = FakeBlogClient(
        {"items": [{
            "title": "<b>로저 구라트</b> 데미세크",
            "description": "<b>로저 구라트</b> 카바 시음기...",
            "link": "https://blog.naver.com/naracellar/224352889386",
            "bloggername": "나라셀라",
            "postdate": "20260721",
        }]},
        thumbnail_html_by_lognum={
            "224352889386": '<meta property="og:image" content="https://blogthumb.pstatic.net/x.jpg">',
        },
    )

    items = collect_naver_blog("로저구라트", "id", "secret", client)

    assert len(items) == 1
    assert items[0].title == "로저 구라트 데미세크"
    assert items[0].excerpt == "로저 구라트 카바 시음기..."
    assert items[0].external_url == "https://blog.naver.com/naracellar/224352889386"
    assert items[0].published_date == "2026-07-21"
    assert items[0].source_name == "블로그: 나라셀라"
    assert items[0].thumbnail_url == "https://blogthumb.pstatic.net/x.jpg"


def test_collect_naver_blog_thumbnail_fetch_failure_falls_back_to_none():
    class BrokenThumbnailClient(FakeBlogClient):
        def get(self, url, params=None, headers=None, timeout=None):
            if "openapi.naver.com" in url:
                return super().get(url, params, headers, timeout)
            raise RuntimeError("network down")

    client = BrokenThumbnailClient({"items": [{
        "title": "제목", "description": "", "link": "https://blog.naver.com/x/1",
        "bloggername": "x", "postdate": "20260721",
    }]})

    items = collect_naver_blog("로저구라트", "id", "secret", client)

    assert items[0].thumbnail_url is None


def test_collect_naver_blog_caps_at_max_items():
    payload = {"items": [
        {"title": f"글{i}", "description": "", "link": f"https://blog.naver.com/x/{i}",
         "bloggername": "x", "postdate": "20260721"}
        for i in range(20)
    ]}
    client = FakeBlogClient(payload)

    items = collect_naver_blog("로저구라트", "id", "secret", client, max_items=15)

    assert len(items) == 15
