import time

import pytest

from app.jobs import JobStore, run_job, run_price_job
from app.sources import NewsSource, YoutubeSource, WassapSource, InternationalSource, SourcesConfig
from app.collectors import CollectedItem, FetchedBody


class _Article:
    def __init__(self):
        self.title = "제목"
        self.excerpt = "요약"
        self.thumbnail_url = None
        self.published_date = "2026-07-01"


def _empty_sources(**overrides) -> SourcesConfig:
    base = dict(news=[], youtube=[], wassap=[], international=[], age_youtube=7)
    base.update(overrides)
    return SourcesConfig(**base)


def _news_deps(**overrides):
    deps = dict(
        fetch_naver_items=lambda query: [],
        fetch_html=lambda url: "<html></html>",
        get_known_brands=lambda: ["몬테스"],
        get_existing_article=lambda url: None,
        insert_article=lambda source_name, url, article, matched, category: 1,
        parse_article_meta=lambda html, fallback: _Article(),
        match_brands=lambda text, brands: ["몬테스"],
        extract_visible_text=lambda html: "본문",
        fetch_blog_items=lambda query: [],
        fetch_youtube_search_items=lambda query: [],
        fetch_web_items=lambda query: [],
        fetch_youtube_items=lambda source: [],
        fetch_wassap_items=lambda source: [],
        fetch_international_items=lambda source: [],
    )
    deps.update(overrides)
    return deps


def test_run_job_succeeds_with_only_news_source():
    store = JobStore()
    job = store.create("몬테스", "몬테스", total=1)
    sources = _empty_sources(news=[NewsSource(id="wine21.com", name="와인21", domain="wine21.com", query="와인21")])

    run_job(job.id, store, sources, "몬테스", "몬테스", **_news_deps(
        fetch_naver_items=lambda query: [{"title": "a", "link": "https://wine21.com/1", "originallink": ""}],
    ))

    result = store.get(job.id)
    assert result.status == "succeeded"
    assert result.done == 4  # 뉴스 소스 1개 + 블로그/유튜브검색/웹검색 각 1(항상 켜짐)
    assert len(result.results) == 1
    assert result.results[0].status == "저장됨"
    assert result.results[0].source_category == "news"
    assert result.results[0].excerpt == "요약"


def test_run_job_news_article_matching_catalog_brand_containing_query_is_kept():
    # matched 브랜드명 안에 검색어가 부분포함되면(공백 무시) 여전히 관련 있다고
    # 봐야 한다 — 예: "베러하프" 검색이 DB의 긴 제품명 "더 베터 하프 말보로..."에
    # 부분포함되는 경우. _brand_relates_to_query가 이 케이스까지 걷어내면 안 된다.
    store = JobStore()
    job = store.create("베러하프", "베러하프", total=1)
    sources = _empty_sources(news=[NewsSource(id="wine21.com", name="와인21", domain="wine21.com", query="")])

    run_job(job.id, store, sources, "베러하프", "베러하프", **_news_deps(
        fetch_naver_items=lambda query: [{"title": "a", "link": "https://wine21.com/1", "originallink": ""}],
        match_brands=lambda text, brands: ["더 베러하프 말보로 소비뇽 블랑"],
    ))

    result = store.get(job.id)
    assert len(result.results) == 1
    assert result.results[0].status == "저장됨"


def test_run_job_news_article_unrelated_to_query_is_skipped():
    # 등록 언론사 도메인이라고 해서 관련 있는 게 아니다 — 애매한 검색어("베러하프"
    # 같은 노래 제목과 겹치는 와인명)는 그 언론사의 완전히 무관한 기사(빵 트렌드
    # 등)도 걸고 올 수 있다. 브랜드 매칭도, 와인 단어도, 검색어 자체도 없으면
    # 조용히 건너뛰어야 한다(실패로 안 잡힘).
    class UnrelatedArticle:
        title = "피할 수 없지만, 늦출 수는 있다...식탁 위 저속노화 트렌드"
        excerpt = "젊어 보이는 외모보다 지속 가능한 건강이 더 중요한 가치로 떠오르며"
        thumbnail_url = None
        published_date = "2026-07-20"

    store = JobStore()
    job = store.create("베러하프", "베러하프", total=1)
    sources = _empty_sources(news=[NewsSource(id="metro.co.kr", name="메트로신문", domain="metro.co.kr", query="")])

    run_job(job.id, store, sources, "베러하프", "베러하프", **_news_deps(
        fetch_naver_items=lambda query: [{"title": "a", "link": "https://metro.co.kr/1", "originallink": ""}],
        parse_article_meta=lambda html, fallback: UnrelatedArticle(),
        match_brands=lambda text, brands: [],
    ))

    result = store.get(job.id)
    assert result.status == "succeeded"
    assert result.results == []


def test_run_job_news_article_matching_unrelated_catalog_brand_is_skipped():
    # 실측(2026-07-31): "레꼴" 검색인데 기사 본문에 전혀 무관한 다른 카탈로그
    # 브랜드("Fantini")가 우연히 언급됐다는 이유만으로 무관한 기사가 결과에
    # 섞여 나왔다 — match_brands는 검색어가 아니라 회사 전체 카탈로그를 스캔하므로
    # "matched가 비어있지 않다"만으로는 관련성 근거가 안 된다. matched된 브랜드가
    # 검색어와 실제로 무관하면 여전히 걸러야 한다.
    class UnrelatedArticle:
        title = "미식의 미학을 아는 샴페인, '로저 바르니에(Roger Barnier)'"
        excerpt = "아버지로부터 포도밭을 물려받아 자신의 이름을 내건 샴페인을 생산하기 시작한다"
        thumbnail_url = None
        published_date = "2026-06-20"

    store = JobStore()
    job = store.create("레꼴", "레꼴", total=1)
    sources = _empty_sources(news=[NewsSource(id="sommeliertimes.com", name="소믈리에타임즈", domain="sommeliertimes.com", query="")])

    run_job(job.id, store, sources, "레꼴", "레꼴", **_news_deps(
        fetch_naver_items=lambda query: [{"title": "a", "link": "https://sommeliertimes.com/1", "originallink": ""}],
        parse_article_meta=lambda html, fallback: UnrelatedArticle(),
        match_brands=lambda text, brands: ["Fantini", "Fonseca"],  # 검색어("레꼴")와 무관한 매칭
    ))

    result = store.get(job.id)
    assert result.status == "succeeded"
    assert result.results == []


def test_run_job_news_article_only_mentioning_region_name_is_skipped():
    # 실측(2026-07-31): "리베라"(나라셀라가 실제 취급하는 이탈리아 와이너리 Rivera)
    # 검색인데 스페인 산지명 "리베라 델 두에로"(Ribera del Duero, 무관)만 언급하는
    # 기사가 걸렸다.
    class RegionOnlyArticle:
        title = "스페인 명산지 기행"
        excerpt = "요약"
        thumbnail_url = None
        published_date = "2026-07-01"

    store = JobStore()
    job = store.create("리베라", "리베라", total=1)
    sources = _empty_sources(news=[NewsSource(id="wine21.com", name="와인21", domain="wine21.com", query="")])

    run_job(job.id, store, sources, "리베라", "리베라", **_news_deps(
        fetch_naver_items=lambda query: [{"title": "a", "link": "https://wine21.com/1", "originallink": ""}],
        parse_article_meta=lambda html, fallback: RegionOnlyArticle(),
        extract_visible_text=lambda html: "이번엔 리베라 델 두에로를 다녀왔다. 유서 깊은 산지다.",
        match_brands=lambda text, brands: [],
    ))

    result = store.get(job.id)
    assert result.results == []


def test_run_job_news_article_mentioning_both_region_and_real_brand_is_kept():
    # 같은 글에 산지명 오탐과 진짜 브랜드 언급이 둘 다 있으면 진짜 매칭 쪽으로 통과돼야 한다.
    class MixedArticle:
        title = "이탈리아 vs 스페인 와인 비교"
        excerpt = "요약"
        thumbnail_url = None
        published_date = "2026-07-01"

    store = JobStore()
    job = store.create("리베라", "리베라", total=1)
    sources = _empty_sources(news=[NewsSource(id="wine21.com", name="와인21", domain="wine21.com", query="")])

    run_job(job.id, store, sources, "리베라", "리베라", **_news_deps(
        fetch_naver_items=lambda query: [{"title": "a", "link": "https://wine21.com/1", "originallink": ""}],
        parse_article_meta=lambda html, fallback: MixedArticle(),
        extract_visible_text=lambda html: "리베라 델 두에로 지역과 달리, 리베라 프리미티보는 풀리아 스타일이다.",
        match_brands=lambda text, brands: [],
    ))

    result = store.get(job.id)
    assert len(result.results) == 1


def test_run_job_news_duplicate_unrelated_to_query_is_skipped():
    store = JobStore()
    job = store.create("베러하프", "베러하프", total=1)
    sources = _empty_sources(news=[NewsSource(id="metro.co.kr", name="메트로신문", domain="metro.co.kr", query="")])

    run_job(job.id, store, sources, "베러하프", "베러하프", **_news_deps(
        fetch_naver_items=lambda query: [{"title": "a", "link": "https://metro.co.kr/1", "originallink": ""}],
        get_existing_article=lambda url: {
            "title": "식탁 위 저속노화 트렌드", "excerpt": "빵과 건강", "thumbnail_url": None, "published_date": None,
        },
        match_brands=lambda text, brands: [],
    ))

    result = store.get(job.id)
    assert result.results == []


def test_run_job_news_search_failure_marks_all_news_sources_failed():
    store = JobStore()
    job = store.create("몬테스", "몬테스", total=2)
    sources = _empty_sources(news=[
        NewsSource(id="wine21.com", name="와인21", domain="wine21.com", query="와인21"),
        NewsSource(id="winein.co.kr", name="와인인", domain="winein.co.kr", query="와인인"),
    ])

    def broken_fetch(query):
        raise RuntimeError("naver api 오류")

    run_job(job.id, store, sources, "몬테스", "몬테스", **_news_deps(fetch_naver_items=broken_fetch))

    result = store.get(job.id)
    assert result.status == "partial"
    assert result.done == 5  # 뉴스 소스 2개 + 블로그/유튜브검색/웹검색 각 1(항상 켜짐)
    assert all(r.status == "실패" for r in result.results)
    assert all(r.reason for r in result.results)


def test_run_job_youtube_source_saves_prebuilt_items():
    store = JobStore()
    job = store.create("몬테스", "몬테스", total=1)
    sources = _empty_sources(youtube=[YoutubeSource(id="bimirya", name="비밀이야", handle="bimirya", channel_id="UCx")])
    item = CollectedItem(
        title="몬테스 알파 리뷰", excerpt="시음 영상", thumbnail_url=None,
        external_url="https://youtu.be/abc", published_date="2026-07-10", source_name="YouTube: 비밀이야",
    )

    run_job(job.id, store, sources, "몬테스", "몬테스", **_news_deps(
        fetch_youtube_items=lambda source: [item],
        match_brands=lambda text, brands: ["몬테스"],
    ))

    result = store.get(job.id)
    assert result.status == "succeeded"
    assert result.done == 4  # 유튜브 소스 1개 + 블로그/유튜브검색/웹검색 각 1(항상 켜짐)
    assert result.results[0].source_category == "youtube"
    assert result.results[0].title == "몬테스 알파 리뷰"
    assert result.results[0].matched_brands == ["몬테스"]


def test_run_job_youtube_item_excerpt_rebuilt_around_query_match():
    # 원본 excerpt엔 검색어가 없고 뒤쪽 본문에만 있는 경우, 카드에 보여줄 excerpt를
    # 검색어 주변으로 다시 잘라줘야 한다 — 안 그러면 왜 매칭됐는지 안 보인다.
    store = JobStore()
    job = store.create("몬테스", "몬테스", total=1)
    sources = _empty_sources(youtube=[YoutubeSource(id="bimirya", name="비밀이야", handle="bimirya", channel_id="UCx")])
    long_excerpt = ("도입부 " * 20) + "이번 영상에서는 몬테스 알파 M을 시음한다 " + ("마무리 " * 20)
    item = CollectedItem(
        title="이번 주 와인 영상", excerpt=long_excerpt, thumbnail_url=None,
        external_url="https://youtu.be/abc", published_date="2026-07-10", source_name="YouTube: 비밀이야",
    )

    run_job(job.id, store, sources, "몬테스", "몬테스", **_news_deps(
        fetch_youtube_items=lambda source: [item],
        match_brands=lambda text, brands: [],
    ))

    result = store.get(job.id)
    assert "몬테스" in result.results[0].excerpt


def test_run_job_youtube_item_unrelated_to_query_is_dropped():
    # 유튜브/와쌉/해외소스 콜렉터는 검색어 없이 채널의 최신 영상을 그대로 반환하므로,
    # 검색어와 무관한(브랜드도 매칭 안 되는) 항목은 결과에서 걸러져야 한다.
    store = JobStore()
    job = store.create("몬테스", "몬테스", total=1)
    sources = _empty_sources(youtube=[YoutubeSource(id="bimirya", name="비밀이야", handle="bimirya", channel_id="UCx")])
    item = CollectedItem(
        title="치킨 먹으러 홍콩 워크숍", excerpt="맛집 탐방", thumbnail_url=None,
        external_url="https://youtu.be/xyz", published_date="2026-07-10", source_name="YouTube: 비밀이야",
    )

    run_job(job.id, store, sources, "몬테스", "몬테스", **_news_deps(
        fetch_youtube_items=lambda source: [item],
        match_brands=lambda text, brands: [],
    ))

    result = store.get(job.id)
    assert result.status == "succeeded"
    assert result.done == 4  # 유튜브 소스 1개 + 블로그/유튜브검색/웹검색 각 1(항상 켜짐)
    assert result.results == []


def test_run_job_blog_item_saved_and_counted_as_one_unit():
    # 블로그·유튜브 검색은 등록 소스 목록이 없다 — sources가 전부 비어 있어도
    # 검색어로 1회씩 실행되고, done/total에도 각각 1만큼만 반영돼야 한다.
    store = JobStore()
    job = store.create("몬테스", "몬테스", total=1)
    sources = _empty_sources()
    item = CollectedItem(
        title="몬테스 알파 후기", excerpt="시음기", thumbnail_url=None,
        external_url="https://blog.naver.com/x/1", published_date="2026-07-20", source_name="블로그: x",
    )

    run_job(job.id, store, sources, "몬테스", "몬테스", **_news_deps(
        fetch_blog_items=lambda query: [item],
        match_brands=lambda text, brands: ["몬테스"],
    ))

    result = store.get(job.id)
    assert result.status == "succeeded"
    assert result.done == 3  # 블로그/유튜브검색/웹검색 각 1(항상 켜짐)
    assert len(result.results) == 1
    assert result.results[0].source_category == "blog"
    assert result.results[0].title == "몬테스 알파 후기"


def test_run_job_blog_item_saved_even_without_literal_query_match():
    # 블로그는 네이버 검색 자체가 이미 query로 걸러준 결과다 — youtube-search와
    # 마찬가지로 title/excerpt에 검색어가 문자 그대로 없어도(브랜드 매칭도 없어도)
    # 걸러지면 안 된다. 안 그러면 실제로 관련 있는 결과까지 다 날아간다.
    store = JobStore()
    job = store.create("로저구라트", "로저구라트", total=1)
    sources = _empty_sources()
    item = CollectedItem(
        title="여름휴가 스파클링 와인 추천 6선", excerpt="", thumbnail_url=None,
        external_url="https://blog.naver.com/x/2", published_date="2026-07-20", source_name="블로그: x",
    )

    run_job(job.id, store, sources, "로저구라트", "로저구라트", **_news_deps(
        fetch_blog_items=lambda query: [item],
        match_brands=lambda text, brands: [],
    ))

    result = store.get(job.id)
    assert len(result.results) == 1
    assert result.results[0].source_category == "blog"


def test_run_job_youtube_search_item_saved_even_without_literal_query_match():
    # 유튜브 검색 결과도 마찬가지 — 영상 제목이 클릭베이트라 검색어를 그대로
    # 담고 있지 않아도(실제 영상 내용은 검색어와 관련 있음) 걸러지면 안 된다.
    # 단, 와인 얘기라는 단서(_mentions_wine)는 있어야 한다 — 아예 없으면 아래
    # test_run_job_youtube_search_item_without_query_or_wine_keyword_is_dropped 참고.
    store = JobStore()
    job = store.create("로저구라트", "로저구라트", total=1)
    sources = _empty_sources()
    item = CollectedItem(
        title="봄에는 그냥 이 와인 드세요", excerpt="", thumbnail_url=None,
        external_url="https://youtu.be/clickbait", published_date="2026-07-20", source_name="YouTube: 검색채널",
    )

    run_job(job.id, store, sources, "로저구라트", "로저구라트", **_news_deps(
        fetch_youtube_search_items=lambda query: [item],
        match_brands=lambda text, brands: [],
    ))

    result = store.get(job.id)
    assert len(result.results) == 1


def test_run_job_youtube_search_item_without_query_or_wine_keyword_is_dropped():
    # "베러하프"(K팝 노래 제목)처럼 흔한 검색어가 와인과 무관한 콘텐츠를 그대로
    # 걸고 오는 경우 — 문자 그대로는 검색어를 담고 있어도 브랜드 매칭도 없고
    # 와인 관련 단어도 하나 없으면 걸러져야 한다.
    store = JobStore()
    job = store.create("베러하프", "베러하프", total=1)
    sources = _empty_sources()
    item = CollectedItem(
        title="JEONGHAN (정한) feat. Omoinotake - 베러하프 [가사]", excerpt="", thumbnail_url=None,
        external_url="https://youtu.be/song", published_date="2026-07-20", source_name="YouTube: Music Time",
    )

    run_job(job.id, store, sources, "베러하프", "베러하프", **_news_deps(
        fetch_youtube_search_items=lambda query: [item],
        match_brands=lambda text, brands: [],
    ))

    result = store.get(job.id)
    assert result.results == []


def test_run_job_blog_fetch_failure_marked_and_isolated():
    store = JobStore()
    job = store.create("몬테스", "몬테스", total=1)
    sources = _empty_sources()

    def broken_blog(query):
        raise RuntimeError("blog api 오류")

    run_job(job.id, store, sources, "몬테스", "몬테스", **_news_deps(fetch_blog_items=broken_blog))

    result = store.get(job.id)
    assert result.status == "partial"
    assert result.done == 3  # 블로그 검색 1(실패) + 유튜브검색/웹검색 각 1(항상 켜짐)
    blog_result = next(r for r in result.results if r.source_category == "blog")
    assert blog_result.status == "실패"


def test_run_job_youtube_search_item_saved_alongside_channel_results():
    # 등록 채널 결과가 하나도 없어도(sources 전부 비어있음) 유튜브 검색은
    # 항상 돌고, 채널 결과와 같은 category="youtube"로 합쳐져야 한다.
    store = JobStore()
    job = store.create("몬테스", "몬테스", total=1)
    sources = _empty_sources()
    item = CollectedItem(
        title="몬테스 시음 영상", excerpt="", thumbnail_url="https://i.ytimg.com/vi/x/hq.jpg",
        external_url="https://youtu.be/x", published_date="2026-07-20", source_name="YouTube: 검색채널",
    )

    run_job(job.id, store, sources, "몬테스", "몬테스", **_news_deps(
        fetch_youtube_search_items=lambda query: [item],
        match_brands=lambda text, brands: ["몬테스"],
    ))

    result = store.get(job.id)
    assert result.status == "succeeded"
    assert result.done == 3  # 블로그/유튜브검색/웹검색 각 1(항상 켜짐)
    assert len(result.results) == 1
    assert result.results[0].source_category == "youtube"
    assert result.results[0].title == "몬테스 시음 영상"
    assert result.results[0].thumbnail_url == "https://i.ytimg.com/vi/x/hq.jpg"


def test_run_job_youtube_search_failure_isolated_from_channel_loop():
    store = JobStore()
    job = store.create("몬테스", "몬테스", total=1)
    sources = _empty_sources(youtube=[YoutubeSource(id="bimirya", name="비밀이야", handle="bimirya", channel_id="UCx")])
    channel_item = CollectedItem(
        title="몬테스 채널 영상", excerpt="", thumbnail_url=None,
        external_url="https://youtu.be/ch1", published_date="2026-07-20", source_name="YouTube: 비밀이야",
    )

    def broken_search(query):
        raise RuntimeError("검색 실패")

    run_job(job.id, store, sources, "몬테스", "몬테스", **_news_deps(
        fetch_youtube_search_items=broken_search,
        fetch_youtube_items=lambda source: [channel_item],
        match_brands=lambda text, brands: ["몬테스"],
    ))

    result = store.get(job.id)
    assert result.status == "partial"
    saved = [r for r in result.results if r.status == "저장됨"]
    failed = [r for r in result.results if r.status == "실패"]
    assert len(saved) == 1 and saved[0].title == "몬테스 채널 영상"
    assert len(failed) == 1 and failed[0].source_category == "youtube"


def test_run_job_wassap_item_saved_even_without_query_or_brand_match():
    # 와쌉은 카페 전체가 와인 커뮤니티라 소스 자체로 이미 관련성이 보장된다 —
    # 최신 10건 중 검색어를 문자 그대로 담은 글이 거의 없어서(2026-07-22 실측),
    # 다른 콜렉터처럼 텍스트 재판정을 걸면 사실상 항상 0건이 된다.
    store = JobStore()
    job = store.create("몬테스", "몬테스", total=1)
    sources = _empty_sources(wassap=[WassapSource(id="winerack24-1", name="와쌉", cafe_id="winerack24", clubid="1")])
    item = CollectedItem(
        title="GS 8월 행사 품목", excerpt="", thumbnail_url=None,
        external_url="https://cafe.naver.com/winerack24/999", published_date=None, source_name="와쌉",
    )

    run_job(job.id, store, sources, "몬테스", "몬테스", **_news_deps(
        fetch_wassap_items=lambda source: [item],
        match_brands=lambda text, brands: [],
    ))

    result = store.get(job.id)
    assert len(result.results) == 1
    assert result.results[0].status == "저장됨"
    assert result.results[0].source_category == "wassap"


def test_run_job_wassap_duplicate_item_not_reinserted():
    store = JobStore()
    job = store.create("몬테스", "몬테스", total=1)
    sources = _empty_sources(wassap=[WassapSource(id="winerack24-1", name="와쌉", cafe_id="winerack24", clubid="1")])
    item = CollectedItem(
        title="몬테스 궁금해요", excerpt="", thumbnail_url=None,
        external_url="https://cafe.naver.com/winerack24/1", published_date=None, source_name="와쌉",
    )
    insert_calls = []

    run_job(job.id, store, sources, "몬테스", "몬테스", **_news_deps(
        fetch_wassap_items=lambda source: [item],
        get_existing_article=lambda url: {
            "title": "몬테스 궁금해요", "excerpt": "", "thumbnail_url": None, "published_date": None,
        },
        insert_article=lambda *a, **k: insert_calls.append(1) or 1,
    ))

    result = store.get(job.id)
    assert result.results[0].status == "중복"
    assert insert_calls == []


def test_run_job_wassap_duplicate_recomputes_excerpt_and_backfills_thumbnail():
    # 예전에 저장된 항목은 DB에 하이라이트 중심 요약도, 썸네일도 없을 수 있다
    # (그 기능들이 생기기 전 저장분) — 중복이어도 이번에 새로 가져온 title/excerpt/
    # thumbnail로 화면 표시만 개선해야 한다(DB는 안 건드림).
    store = JobStore()
    job = store.create("몬테스", "몬테스", total=1)
    sources = _empty_sources(wassap=[WassapSource(id="winerack24-1", name="와쌉", cafe_id="winerack24", clubid="1")])
    long_excerpt = ("도입부 " * 20) + "이번 글에서는 몬테스 알파를 소개한다 " + ("마무리 " * 20)
    item = CollectedItem(
        title="와인 추천", excerpt=long_excerpt, thumbnail_url="https://example.com/fresh.jpg",
        external_url="https://cafe.naver.com/winerack24/1", published_date=None, source_name="와쌉",
    )

    run_job(job.id, store, sources, "몬테스", "몬테스", **_news_deps(
        fetch_wassap_items=lambda source: [item],
        match_brands=lambda text, brands: ["몬테스"],
        get_existing_article=lambda url: {
            "title": "와인 추천", "excerpt": "도입부만 저장된 예전 요약", "thumbnail_url": None, "published_date": None,
        },
    ))

    result = store.get(job.id)
    assert result.results[0].status == "중복"
    assert "몬테스" in result.results[0].excerpt
    assert result.results[0].thumbnail_url == "https://example.com/fresh.jpg"


def test_run_job_international_source_failure_isolated_from_others():
    store = JobStore()
    job = store.create("몬테스", "몬테스", total=2)
    sources = _empty_sources(international=[
        InternationalSource(id="decanter", name="Decanter", url="https://decanter.com"),
        InternationalSource(id="oiv", name="OIV", url="https://oiv.int"),
    ])
    good_item = CollectedItem(
        title="몬테스 관련 소식", excerpt="", thumbnail_url=None,
        external_url="https://oiv.int/1", published_date=None, source_name="OIV",
    )

    def flaky_intl(source):
        if source.name == "Decanter":
            raise RuntimeError("파싱 실패")
        return [good_item]

    run_job(job.id, store, sources, "몬테스", "몬테스", **_news_deps(
        fetch_international_items=flaky_intl,
        match_brands=lambda text, brands: [],
    ))

    result = store.get(job.id)
    assert result.status == "partial"
    assert result.done == 5  # 해외소스 2개 + 블로그/유튜브검색/웹검색 각 1(항상 켜짐)
    statuses = {r.source_name: r.status for r in result.results}
    assert statuses["Decanter"] == "실패"
    assert statuses["OIV"] == "저장됨"


def test_run_job_fails_immediately_when_brand_list_lookup_fails():
    store = JobStore()
    job = store.create("몬테스", "몬테스", total=1)
    sources = _empty_sources(news=[NewsSource(id="wine21.com", name="와인21", domain="wine21.com", query="와인21")])

    def broken_get_known_brands():
        raise RuntimeError("DB 연결 실패")

    run_job(job.id, store, sources, "몬테스", "몬테스", **_news_deps(get_known_brands=broken_get_known_brands))

    result = store.get(job.id)
    assert result.status == "failed"
    assert "DB 연결 실패" in result.error


def test_job_store_update_rejects_unknown_field():
    store = JobStore()
    job = store.create("몬테스", "몬테스", total=1)

    with pytest.raises(AttributeError):
        store.update(job.id, nonexistent_field="x")


def test_run_job_stops_early_when_deadline_already_passed():
    store = JobStore()
    job = store.create("몬테스", "몬테스", total=1)
    sources = _empty_sources(news=[NewsSource(id="wine21.com", name="와인21", domain="wine21.com", query="와인21")])

    run_job(job.id, store, sources, "몬테스", "몬테스", **_news_deps(
        fetch_naver_items=lambda query: [{"title": "a", "link": "https://wine21.com/1", "originallink": ""}],
        deadline=time.monotonic() - 1,
    ))

    result = store.get(job.id)
    assert result.status == "failed"
    assert "시간 제한" in result.error
    assert result.done == 0


def test_run_job_news_insert_receives_news_category():
    store = JobStore()
    job = store.create("몬테스", "몬테스", total=1)
    sources = _empty_sources(news=[NewsSource(id="wine21.com", name="와인21", domain="wine21.com", query="와인21")])
    captured = []

    def capturing_insert(source_name, url, article, matched, category):
        captured.append(category)
        return 1

    run_job(job.id, store, sources, "몬테스", "몬테스", **_news_deps(
        fetch_naver_items=lambda query: [{"title": "a", "link": "https://wine21.com/1", "originallink": ""}],
        insert_article=capturing_insert,
    ))

    assert captured == ["news"]


def test_run_job_youtube_insert_receives_youtube_category():
    store = JobStore()
    job = store.create("몬테스", "몬테스", total=1)
    sources = _empty_sources(youtube=[YoutubeSource(id="bimirya", name="비밀이야", handle="bimirya", channel_id="UCx")])
    item = CollectedItem(
        title="몬테스 알파 리뷰", excerpt="", thumbnail_url=None,
        external_url="https://youtu.be/abc", published_date="2026-07-10", source_name="YouTube: 비밀이야",
    )
    captured = []

    def capturing_insert(source_name, url, article, matched, category):
        captured.append(category)
        return 1

    run_job(job.id, store, sources, "몬테스", "몬테스", **_news_deps(
        fetch_youtube_items=lambda source: [item],
        match_brands=lambda text, brands: ["몬테스"],
        insert_article=capturing_insert,
    ))

    assert captured == ["youtube"]


def _price_deps(**overrides):
    deps = dict(
        fetch_blog_items=lambda query: [],
        fetch_wassap_items=lambda source: [],
        fetch_blog_body=lambda url: None,
        fetch_wassap_body=lambda source, url: None,
        insert_channel_price=lambda *a, **k: 1,
        get_price_history=lambda query: [],
        extract_image_price=None,
    )
    deps.update(overrides)
    return deps


def test_run_price_job_extracts_and_stores_blog_prices():
    store = JobStore()
    job = store.create("몬테스", "", total=1)
    sources = _empty_sources()
    inserted = []

    run_price_job(job.id, store, sources, "몬테스", "", **_price_deps(
        fetch_blog_items=lambda query: [CollectedItem(
            title="후기", excerpt="요약", thumbnail_url=None,
            external_url="https://blog.naver.com/naracellar/1", published_date="2026-06-15",
            source_name="블로그: 나라셀라",
        )],
        fetch_blog_body=lambda url: "몬테스 이마트 29,800원~33,000원 완전 혜자",
        insert_channel_price=lambda *a, **k: inserted.append(a) or 1,
        get_price_history=lambda query: [{
            "channel": "이마트", "price_low": 29800, "price_high": 33000,
            "year_month": "2026-06", "source_type": "blog", "source_url": "https://blog.naver.com/naracellar/1",
        }],
    ))

    result = store.get(job.id)
    assert result.status == "succeeded"
    assert result.price_results == [{
        "channel": "이마트", "year_month": "2026-06", "price_low": 29800, "price_high": 33000,
        "source_urls": ["https://blog.naver.com/naracellar/1"],
    }]
    assert len(inserted) == 1
    assert inserted[0][:2] == ("몬테스", "이마트")


def test_run_price_job_lists_checked_items_even_when_no_price_found():
    # 사용자가 "왜 0건이지?"를 직접 확인할 수 있도록, 가격을 못 찾은 경우에도
    # 실제로 검색해서 본문까지 확인한 게시글 목록(제목/링크)은 남겨야 한다.
    store = JobStore()
    job = store.create("케이머스", "", total=1)
    sources = _empty_sources()

    run_price_job(job.id, store, sources, "케이머스", "", **_price_deps(
        fetch_blog_items=lambda query: [CollectedItem(
            title="케이머스 시음기", excerpt="요약", thumbnail_url=None,
            external_url="https://blog.naver.com/someone/1", published_date="2026-06-15",
            source_name="블로그: someone",
        )],
        fetch_blog_body=lambda url: "케이머스 마셔봤다. 가격 얘기는 없고 시음 후기만 있음",
    ))

    result = store.get(job.id)
    assert result.price_results == []
    assert result.price_checked_items == [{
        "source_type": "blog", "source_name": "블로그: someone", "title": "케이머스 시음기",
        "external_url": "https://blog.naver.com/someone/1", "published_date": "2026-06-15",
        "status": "no_price",  # 검색어는 나오는 글 — 가격만 없었다
    }]


def test_run_price_job_one_failing_insert_does_not_block_siblings():
    # 같은 포스트에서 여러 채널/가격이 나올 때, 하나의 insert 실패가 같은
    # 포스트의 나머지 값 처리를 막으면 안 된다(각 값은 독립된 try/except).
    store = JobStore()
    job = store.create("몬테스", "", total=1)
    sources = _empty_sources()
    insert_calls = []

    def flaky_insert(wine_query, channel, price_low, price_high, year_month, source_type, source_url):
        insert_calls.append(channel)
        if channel == "이마트":
            raise RuntimeError("db down for 이마트")
        return 1

    run_price_job(job.id, store, sources, "몬테스", "", **_price_deps(
        fetch_blog_items=lambda query: [CollectedItem(
            title="후기", excerpt="요약", thumbnail_url=None,
            external_url="https://blog.naver.com/naracellar/1", published_date="2026-06-15",
            source_name="블로그: 나라셀라",
        )],
        fetch_blog_body=lambda url: "몬테스 이마트 29,800원\n몬테스 코스트코 25,000원",
        insert_channel_price=flaky_insert,
    ))

    assert insert_calls == ["이마트", "코스트코"]  # 둘 다 시도됨 — 이마트 실패가 코스트코를 막지 않음
    result = store.get(job.id)
    assert result.status == "succeeded"  # insert 실패는 로그만, 전체 job은 계속 성공 처리


def test_run_price_job_skips_post_about_different_product_of_same_brand():
    # 실측(2026-09-03): "몬테스 클래식" 검색에 네이버 블로그가 "몬테스 알파
    # 스페셜 퀴베" 글을 돌려줬고, 그 글의 가격이 클래식 가격으로 저장됐다.
    # 검색어가 제목·본문에 아예 없는 글은 통째로 버려야 한다.
    store = JobStore()
    job = store.create("몬테스 클래식", "", total=1)
    sources = _empty_sources()
    inserted = []

    run_price_job(job.id, store, sources, "몬테스 클래식", "", **_price_deps(
        fetch_blog_items=lambda query: [CollectedItem(
            title="39. 몬테스 알파 스페셜 퀴베 카버네 소비뇽 2022", excerpt="요약", thumbnail_url=None,
            external_url="https://blog.naver.com/mimikim0/224344190304", published_date="2026-07-12",
            source_name="블로그: 김미미",
        )],
        fetch_blog_body=lambda url: "몬테스 알파 스페셜 퀴베 GS25에서 32,900원에 샀다",
        insert_channel_price=lambda *a, **k: inserted.append(a) or 1,
    ))

    result = store.get(job.id)
    assert inserted == []  # 다른 제품 글 — 가격 저장 안 함
    assert result.price_checked_items[0]["status"] == "unrelated"


def test_run_price_job_comparison_post_binds_only_the_searched_products_line():
    # 검색어가 나오는 글이라도 같은 브랜드 다른 제품 가격이 같이 적혀 있으면
    # 그 줄은 버린다 — 검색한 제품 줄만 저장한다.
    store = JobStore()
    job = store.create("몬테스 클래식", "", total=1)
    sources = _empty_sources()
    inserted = []

    run_price_job(job.id, store, sources, "몬테스 클래식", "", **_price_deps(
        fetch_blog_items=lambda query: [CollectedItem(
            title="몬테스 클래식 vs 알파 가격 비교", excerpt="요약", thumbnail_url=None,
            external_url="https://blog.naver.com/someone/2", published_date="2026-07-01",
            source_name="블로그: someone",
        )],
        fetch_blog_body=lambda url: "몬테스 알파 이마트 45,000원\n몬테스 클래식 GS25 19,900원",
        insert_channel_price=lambda *a, **k: inserted.append(a) or 1,
    ))

    assert [(a[1], a[2]) for a in inserted] == [("GS25", 19900)]  # 알파(이마트 45,000)는 제외


def test_run_price_job_blog_search_query_includes_price_keyword():
    # 블로그 검색은 시음기가 대부분이라 검색어에 "가격"을 붙여 좁힌다.
    # 와쌉은 특가 글만 올라오는 카페라 검색어를 그대로 쓴다.
    store = JobStore()
    job = store.create("몬테스 클래식", "", total=1)
    wassap_source = WassapSource(
        id="winerack24-10050146", name="와쌉", cafe_id="winerack24", clubid="10050146",
        cafe_numeric_id="20564405",
    )
    sources = _empty_sources(wassap=[wassap_source])
    blog_queries, wassap_calls = [], []

    run_price_job(job.id, store, sources, "몬테스 클래식", "", **_price_deps(
        fetch_blog_items=lambda query: blog_queries.append(query) or [],
        fetch_wassap_items=lambda source: wassap_calls.append(source.name) or [],
    ))

    assert blog_queries == ["몬테스 클래식 가격"]
    assert wassap_calls == ["와쌉"]


def test_run_price_job_body_fetch_failure_does_not_fail_whole_job():
    store = JobStore()
    job = store.create("몬테스", "", total=1)
    sources = _empty_sources()

    def broken_fetch_blog_body(url):
        raise RuntimeError("network down")

    run_price_job(job.id, store, sources, "몬테스", "", **_price_deps(
        fetch_blog_items=lambda query: [CollectedItem(
            title="후기", excerpt="요약", thumbnail_url=None,
            external_url="https://blog.naver.com/naracellar/1", published_date="2026-06-15",
            source_name="블로그: 나라셀라",
        )],
        fetch_blog_body=broken_fetch_blog_body,
    ))

    result = store.get(job.id)
    assert result.status == "succeeded"
    assert result.price_results == []


def test_run_price_job_extracts_wassap_prices():
    store = JobStore()
    job = store.create("몬테스", "", total=1)
    wassap_source = WassapSource(
        id="winerack24-10050146", name="와쌉", cafe_id="winerack24", clubid="10050146",
        cafe_numeric_id="20564405",
    )
    sources = _empty_sources(wassap=[wassap_source])
    seen_args = []

    def fake_fetch_wassap_body(source, url):
        seen_args.append((source.cafe_numeric_id, url))
        return "CU 21,000원에 픽업했어요"

    run_price_job(job.id, store, sources, "몬테스", "", **_price_deps(
        fetch_wassap_items=lambda source: [CollectedItem(
            title="후기", excerpt="요약", thumbnail_url=None,
            external_url="https://cafe.naver.com/winerack24/369628", published_date="2026-08-31",
            source_name="와쌉",
        )],
        fetch_wassap_body=fake_fetch_wassap_body,
        get_price_history=lambda query: [{
            "channel": "CU", "price_low": 21000, "price_high": 21000,
            "year_month": "2026-08", "source_type": "wassap", "source_url": "https://cafe.naver.com/winerack24/369628",
        }],
    ))

    result = store.get(job.id)
    assert result.price_results == [{
        "channel": "CU", "year_month": "2026-08", "price_low": 21000, "price_high": 21000,
        "source_urls": ["https://cafe.naver.com/winerack24/369628"],
    }]
    assert seen_args == [("20564405", "https://cafe.naver.com/winerack24/369628")]


def test_run_price_job_skips_body_fetch_when_deadline_already_passed():
    store = JobStore()
    job = store.create("몬테스", "", total=1)
    sources = _empty_sources()

    def must_not_be_called(*a, **k):
        raise AssertionError("마감 이후에는 호출되면 안 됨")

    run_price_job(job.id, store, sources, "몬테스", "", **_price_deps(
        fetch_blog_items=lambda query: [CollectedItem(
            title="후기", excerpt="요약", thumbnail_url=None,
            external_url="https://blog.naver.com/naracellar/1", published_date="2026-06-15",
            source_name="블로그: 나라셀라",
        )],
        fetch_blog_body=must_not_be_called,
        insert_channel_price=must_not_be_called,
        deadline=time.monotonic() - 1,
    ))

    result = store.get(job.id)
    assert result.status == "failed"
    assert result.price_results == []


def test_run_price_job_history_lookup_failure_marks_partial():
    store = JobStore()
    job = store.create("몬테스", "", total=1)
    sources = _empty_sources()

    def broken_history(query):
        raise RuntimeError("db down")

    run_price_job(job.id, store, sources, "몬테스", "", **_price_deps(get_price_history=broken_history))

    result = store.get(job.id)
    assert result.status == "partial"
    assert result.price_results == []


def test_run_price_job_accepts_fetched_body_object():
    store = JobStore()
    job = store.create("몬테스", "", total=1)
    sources = _empty_sources()

    run_price_job(job.id, store, sources, "몬테스", "", **_price_deps(
        fetch_blog_items=lambda query: [CollectedItem(
            title="후기", excerpt="", thumbnail_url=None,
            external_url="https://blog.naver.com/x/9", published_date="2026-06-15",
            source_name="블로그: x",
        )],
        fetch_blog_body=lambda url: FetchedBody(text="몬테스 이마트 29,800원", image_urls=["https://img/a.png"]),
    ))

    assert store.get(job.id).price_checked_items[0]["status"] == "priced"


def test_run_price_job_still_accepts_plain_string_body():
    store = JobStore()
    job = store.create("몬테스", "", total=1)
    sources = _empty_sources()

    run_price_job(job.id, store, sources, "몬테스", "", **_price_deps(
        fetch_blog_items=lambda query: [CollectedItem(
            title="후기", excerpt="", thumbnail_url=None,
            external_url="https://blog.naver.com/x/10", published_date="2026-06-15",
            source_name="블로그: x",
        )],
        fetch_blog_body=lambda url: "몬테스 이마트 29,800원",
    ))

    assert store.get(job.id).price_checked_items[0]["status"] == "priced"


def test_run_price_job_falls_back_to_image_when_text_has_no_price():
    # 스펙의 근거 사례: GS25 와쌉 글은 본문에 가격 텍스트가 없고 결제화면 캡처
    # 이미지에만 15,920원이 찍혀 있다.
    store = JobStore()
    job = store.create("베터하프", "", total=1)
    sources = _empty_sources()
    inserted = []

    run_price_job(job.id, store, sources, "베터하프", "", **_price_deps(
        fetch_blog_items=lambda query: [CollectedItem(
            title="GS25 오늘의 와인 - 베터하프 문의", excerpt="", thumbnail_url=None,
            external_url="https://blog.naver.com/x/1", published_date="2026-08-04",
            source_name="블로그: x",
        )],
        fetch_blog_body=lambda url: FetchedBody(
            text="베터하프 이거 문의드려요", image_urls=["https://img/pay.png"]),
        extract_image_price=lambda urls: 15920,
        insert_channel_price=lambda *a, **k: inserted.append(a) or 1,
    ))

    result = store.get(job.id)
    assert result.price_checked_items[0]["status"] == "priced_from_image"
    assert inserted[0] == ("베터하프", "GS25", 15920, 15920, "2026-08", "blog_img", "https://blog.naver.com/x/1")


def test_run_price_job_does_not_use_images_when_text_price_found():
    # 본문에서 가격을 찾았으면 이미지는 보지 않는다 — 호출 최소화.
    store = JobStore()
    job = store.create("몬테스", "", total=1)
    sources = _empty_sources()
    image_calls = []

    run_price_job(job.id, store, sources, "몬테스", "", **_price_deps(
        fetch_blog_items=lambda query: [CollectedItem(
            title="후기", excerpt="", thumbnail_url=None,
            external_url="https://blog.naver.com/x/2", published_date="2026-06-15",
            source_name="블로그: x",
        )],
        fetch_blog_body=lambda url: FetchedBody(
            text="몬테스 이마트 29,800원", image_urls=["https://img/a.png"]),
        extract_image_price=lambda urls: image_calls.append(urls) or 9999,
    ))

    assert image_calls == []
    assert store.get(job.id).price_checked_items[0]["status"] == "priced"


def test_run_price_job_skips_image_price_when_channel_ambiguous():
    # 이미지에서 가격을 읽어도 글에서 채널이 하나로 확정 안 되면 저장하지 않는다.
    store = JobStore()
    job = store.create("베터하프", "", total=1)
    sources = _empty_sources()
    inserted = []

    run_price_job(job.id, store, sources, "베터하프", "", **_price_deps(
        fetch_blog_items=lambda query: [CollectedItem(
            title="이마트랑 GS25 비교", excerpt="", thumbnail_url=None,
            external_url="https://blog.naver.com/x/3", published_date="2026-08-04",
            source_name="블로그: x",
        )],
        fetch_blog_body=lambda url: FetchedBody(text="베터하프 어디가 싼가요", image_urls=["https://img/a.png"]),
        extract_image_price=lambda urls: 15920,
        insert_channel_price=lambda *a, **k: inserted.append(a) or 1,
    ))

    assert inserted == []
    assert store.get(job.id).price_checked_items[0]["status"] == "no_price"
