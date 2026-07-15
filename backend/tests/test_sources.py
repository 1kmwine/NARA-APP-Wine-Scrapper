from app.sources import SOURCES, source_by_id, url_matches_domain


def test_has_twelve_sources():
    assert len(SOURCES) == 12


def test_ids_match_frontend_defaults():
    ids = {s.id for s in SOURCES}
    assert ids == {
        "sommelier", "wine21", "winein", "hankyung", "mk", "chosun",
        "decanter", "ws", "js", "rp", "wspec", "wmag",
    }


def test_source_by_id_found():
    source = source_by_id("wine21")
    assert source is not None
    assert source.domain == "wine21.com"


def test_source_by_id_missing_returns_none():
    assert source_by_id("nope") is None


def test_url_matches_domain():
    assert url_matches_domain("https://www.wine21.com/news/1", "wine21.com")
    assert not url_matches_domain("https://example.com/other", "wine21.com")
