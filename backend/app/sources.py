from __future__ import annotations
from dataclasses import dataclass, field


@dataclass(frozen=True)
class NewsSource:
    id: str          # 소스 도메인을 그대로 사용 (예: "wine21.com") — 고유하고 안정적
    name: str         # 매체명 (예: "와인21")
    domain: str        # 도메인 매칭용
    query: str = ""      # scraping-sources.md의 검색어 컬럼


@dataclass(frozen=True)
class YoutubeSource:
    id: str          # 핸들을 id로 사용 (Channel ID는 비어있을 수 있어 안정적이지 않음)
    name: str         # 채널명
    handle: str        # youtube.com/@handle의 handle
    channel_id: str = ""  # 비어있으면 collectors.py가 핸들 페이지에서 자동 추출


@dataclass(frozen=True)
class WassapSource:
    id: str          # f"{cafe_id}-{clubid}"
    name: str          # 표시명 (기본 "와쌉")
    cafe_id: str        # URL 경로 세그먼트 (예: "winerack24")
    clubid: str          # 네이버 카페 clubid (구 API용, ArticleList.nhn 등)
    # 신형 카페(ca-fe.pstatic.net SPA)의 내부 검색 API가 쓰는 별도의 숫자 ID —
    # clubid와 무관한 다른 값이라(2026-07-22 확인: winerack24는 clubid 10050146,
    # cafeId 20564405) 자동 변환 불가, 브라우저에서 새 카페 검색 페이지
    # 열어(cafe.naver.com/f-e/cafes/{cafeId}/...) URL에서 직접 확인해 채워야
    # 한다. 비어 있으면 search_wassap이 이 소스를 건너뛴다.
    cafe_numeric_id: str = ""


@dataclass(frozen=True)
class InternationalSource:
    id: str          # 소스명을 슬러그화 (예: "decanter", "wine-spectator")
    name: str         # 소스명 (collectors.py의 파서 디스패치 키로도 쓰임 — 예: "Decanter")
    url: str            # 목록 페이지 URL


@dataclass(frozen=True)
class SourcesConfig:
    news: list[NewsSource] = field(default_factory=list)
    youtube: list[YoutubeSource] = field(default_factory=list)
    wassap: list[WassapSource] = field(default_factory=list)
    international: list[InternationalSource] = field(default_factory=list)
    age_youtube: int = 7  # scraping-sources.md 수집쿼리 블록의 최근_유튜브_일수

    def total_count(self) -> int:
        # +3은 블로그 검색 + 유튜브 검색 + 웹 검색(DuckDuckGo) — 셋 다 등록 소스
        # 목록이 없는 항상-켜짐 검색이라(블로거는 수천 명, 유튜브 등록 채널
        # 11개·해외소스 3곳으로는 커버리지가 너무 좁음) "검색어로 1회 검색"이라는
        # 단일 작업으로 센다.
        return len(self.news) + len(self.youtube) + len(self.wassap) + len(self.international) + 3
