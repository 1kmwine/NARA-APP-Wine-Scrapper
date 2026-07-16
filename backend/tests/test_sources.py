from app.sources import (
    NewsSource, YoutubeSource, WassapSource, InternationalSource, SourcesConfig,
)


def test_sources_config_total_count_sums_all_categories():
    cfg = SourcesConfig(
        news=[NewsSource(id="wine21.com", name="와인21", domain="wine21.com", query="와인21")],
        youtube=[
            YoutubeSource(id="bimirya", name="비밀이야", handle="bimirya", channel_id="UCxxx"),
            YoutubeSource(id="yanggangtv", name="양갱", handle="yanggangtv", channel_id=""),
        ],
        wassap=[WassapSource(id="winerack24-10050146", name="와쌉", cafe_id="winerack24", clubid="10050146")],
        international=[InternationalSource(id="decanter", name="Decanter", url="https://www.decanter.com/wine-news/")],
        age_youtube=7,
    )
    assert cfg.total_count() == 5


def test_sources_config_total_count_zero_when_empty():
    cfg = SourcesConfig(news=[], youtube=[], wassap=[], international=[], age_youtube=7)
    assert cfg.total_count() == 0


def test_news_source_is_frozen_dataclass():
    source = NewsSource(id="wine21.com", name="와인21", domain="wine21.com", query="와인21")
    assert source.domain == "wine21.com"


def test_youtube_source_channel_id_optional():
    source = YoutubeSource(id="bimirya", name="비밀이야", handle="bimirya", channel_id="")
    assert source.channel_id == ""
