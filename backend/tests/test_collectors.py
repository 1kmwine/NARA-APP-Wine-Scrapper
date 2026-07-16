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


def _channel_page(video_id, title, date_text):
    data = {
        "contents": {"twoColumnBrowseResultsRenderer": {"tabs": [
            {},
            {"tabRenderer": {"content": {"richGridRenderer": {"contents": [
                {"richItemRenderer": {"content": {"videoRenderer": {
                    "videoId": video_id,
                    "title": {"runs": [{"text": title}]},
                    "publishedTimeText": {"simpleText": date_text},
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


def test_collect_wassap_sorts_by_comment_count_desc():
    html = (
        '<a href="/ArticleRead.nhn?clubid=10050146&amp;articleid=1" title="답0/댓1">'
        '<div class="ellipsis tcol-c">댓글적음</div></a>'
        '<a href="/ArticleRead.nhn?clubid=10050146&amp;articleid=2" title="답0/댓20">'
        '<div class="ellipsis tcol-c">댓글많음</div></a>'
    )
    source = WassapSource(id="winerack24-10050146", name="와쌉", cafe_id="winerack24", clubid="10050146")
    client = FakeWassapClient(html)

    items = collect_wassap(source, client, naver_cookie="fake-cookie")

    assert items[0].title == "댓글많음"
    assert items[1].title == "댓글적음"


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


def test_collect_international_unsupported_source_raises():
    source = InternationalSource(id="jamessuckling", name="James Suckling", url="https://www.jamessuckling.com/")
    client = FakeInternationalClient({})
    import pytest
    with pytest.raises(NotImplementedError):
        collect_international(source, client, translate=_identity_translate)
