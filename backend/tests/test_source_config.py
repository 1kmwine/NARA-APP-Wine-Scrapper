from app.source_config import parse_sources_document

FIXTURE = """# 스크래핑 소스 목록

## 국내 뉴스·매거진 **[브리핑]**

| 매체 | 분류 | 검색어 | URL |
|------|------|--------|-----|
| 소믈리에타임즈 | 매거진 | 소믈리에타임즈 | https://www.sommeliertimes.com/ |
| 와인21 | 매거진 | 와인21 | https://www.wine21.com/11_news/news_list.html |
| 한국경제 | 뉴스 | 한국경제 와인 | https://www.hankyung.com/ |

## 뉴스룸 **[브리핑]**

| 매체 | URL | 방식 |
|------|-----|------|
| 나라셀라 칼럼 | https://www.naracellar.com/bbs/board.php?bo_table=column | board |

## 유튜브 **[브리핑]**

| 채널명 | URL | Channel ID |
|--------|-----|-----------|
| 비밀이야 | https://www.youtube.com/@bimirya | UCaKQ7_GT0k8u_sL0nE2tgkA |
| 양갱 | https://www.youtube.com/@yanggangtv | UCohsv4KNeRzmj7E6ipE8COA |
| 신규채널 | https://www.youtube.com/@newchannel |  |

## 커뮤니티

### 와쌉 (네이버 카페) **[브리핑]**

- https://cafe.naver.com/winerack24 (clubid: 10050146)

### 네이버 블로그 **[공통]**

내용

## 해외·통계·이벤트 소스 **[브리핑]**

| 소스 | 상태 | URL | 비고 |
|------|------|-----|------|
| Decanter | ✅ 수집 중 | https://www.decanter.com/wine-news/ | 비고1 |
| Wine Spectator | ✅ 수집 중 | https://www.winespectator.com/ | 비고2 |
| Wine Enthusiast | ❌ 수집 불가 | https://www.wineenthusiast.com/ | 403 |
| Wine Advocate | ❌ 미확인 | https://winejournal.robertparker.com/ | TODO |

| 소스군 | 항목 | 상태 |
|--------|------|------|
| 국내 통계 | 가처분소득 | 미수집 |

```수집쿼리
와쌉_clubid: 10050146
최근_유튜브_일수: 5
```
"""


def test_parses_news_sources_with_domain():
    cfg = parse_sources_document(FIXTURE)
    assert len(cfg.news) == 3
    wine21 = next(s for s in cfg.news if s.name == "와인21")
    assert wine21.domain == "wine21.com"
    assert wine21.query == "와인21"
    assert wine21.id == "wine21.com"


def test_parses_youtube_sources_including_blank_channel_id():
    cfg = parse_sources_document(FIXTURE)
    assert len(cfg.youtube) == 3
    bimirya = next(s for s in cfg.youtube if s.handle == "bimirya")
    assert bimirya.channel_id == "UCaKQ7_GT0k8u_sL0nE2tgkA"
    new_channel = next(s for s in cfg.youtube if s.handle == "newchannel")
    assert new_channel.channel_id == ""


def test_parses_wassap_source_from_bullet():
    cfg = parse_sources_document(FIXTURE)
    assert len(cfg.wassap) == 1
    assert cfg.wassap[0].cafe_id == "winerack24"
    assert cfg.wassap[0].clubid == "10050146"


def test_parses_only_checked_international_sources():
    cfg = parse_sources_document(FIXTURE)
    names = {s.name for s in cfg.international}
    assert names == {"Decanter", "Wine Spectator"}


def test_international_second_summary_table_not_parsed_as_sources():
    cfg = parse_sources_document(FIXTURE)
    assert all(s.name != "국내 통계" for s in cfg.international)


def test_parses_age_youtube_from_query_block():
    cfg = parse_sources_document(FIXTURE)
    assert cfg.age_youtube == 5


def test_age_youtube_defaults_to_seven_when_block_missing():
    minimal = "## 국내 뉴스·매거진\n\n| 매체 | 분류 | 검색어 | URL |\n|--|--|--|--|\n"
    cfg = parse_sources_document(minimal)
    assert cfg.age_youtube == 7
