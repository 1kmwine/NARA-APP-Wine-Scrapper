from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    domain: str


# js/app.js의 DEFAULT_SOURCES와 id/도메인을 반드시 동일하게 유지한다.
SOURCES: list[Source] = [
    Source("sommelier", "소믈리에 타임즈", "sommeliertimes.com"),
    Source("wine21", "와인21", "wine21.com"),
    Source("winein", "와인인", "winein.co.kr"),
    Source("hankyung", "한국경제", "hankyung.com"),
    Source("mk", "매일경제", "mk.co.kr"),
    Source("chosun", "조선비즈", "biz.chosun.com"),
    Source("decanter", "Decanter", "decanter.com"),
    Source("ws", "Wine-Searcher", "wine-searcher.com"),
    Source("js", "James Suckling", "jamessuckling.com"),
    Source("rp", "Wine Advocate", "robertparker.com"),
    Source("wspec", "Wine Spectator", "winespectator.com"),
    Source("wmag", "Wine Enthusiast", "winemag.com"),
]

_SOURCES_BY_ID = {s.id: s for s in SOURCES}


def source_by_id(source_id: str) -> Source | None:
    return _SOURCES_BY_ID.get(source_id)
