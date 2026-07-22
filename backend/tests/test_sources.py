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
    assert cfg.total_count() == 7  # 등록 소스 5개 + 블로그 검색 1 + 유튜브 검색 1


def test_sources_config_total_count_counts_always_on_searches_even_when_everything_else_empty():
    # 블로그·유튜브 검색은 등록 소스 목록이 없는 항상-켜짐 검색이라, 다른
    # 카테고리가 전부 비어 있어도 total_count는 0이 아니라 2여야 한다.
    cfg = SourcesConfig(news=[], youtube=[], wassap=[], international=[], age_youtube=7)
    assert cfg.total_count() == 2


def test_news_source_is_frozen_dataclass():
    source = NewsSource(id="wine21.com", name="와인21", domain="wine21.com", query="와인21")
    assert source.domain == "wine21.com"


def test_youtube_source_channel_id_optional():
    source = YoutubeSource(id="bimirya", name="비밀이야", handle="bimirya", channel_id="")
    assert source.channel_id == ""
