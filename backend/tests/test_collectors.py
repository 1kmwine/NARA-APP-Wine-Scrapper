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
