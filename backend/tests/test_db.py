import pytest

from app.db import get_known_brands, find_english_name, article_exists, get_article, insert_article, ensure_channel_prices_table, insert_channel_price
from app.parse import ParsedArticle


class FakeCursor:
    def __init__(self, fetch_results=None, fail_after_n_executes=None):
        self.executed = []
        self._fetch_results = fetch_results or []
        self.lastrowid = 42
        self._fail_after_n_executes = fail_after_n_executes

    def execute(self, sql, params=None):
        if self._fail_after_n_executes is not None and len(self.executed) >= self._fail_after_n_executes:
            raise RuntimeError("simulated execute failure")
        self.executed.append((sql.strip(), params))

    def fetchall(self):
        return self._fetch_results

    def fetchone(self):
        return self._fetch_results[0] if self._fetch_results else None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeConnection:
    def __init__(self, fetch_results=None, fail_after_n_executes=None):
        self._cursor = FakeCursor(fetch_results, fail_after_n_executes=fail_after_n_executes)
        self.committed = False
        self.rolled_back = False

    def cursor(self):
        return self._cursor

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


def test_get_known_brands_returns_distinct_names():
    conn = FakeConnection(fetch_results=[("Montes",), ("Kaiken",)])
    assert get_known_brands(conn) == ["Montes", "Kaiken"]


def test_find_english_name_returns_matching_row():
    conn = FakeConnection(fetch_results=[("The Better half Marlborough Sauvignon Blanc",)])
    assert find_english_name(conn, "베터하프") == "The Better half Marlborough Sauvignon Blanc"


def test_find_english_name_returns_none_when_no_match():
    conn = FakeConnection(fetch_results=[])
    assert find_english_name(conn, "존재하지않음") is None


def test_find_english_name_returns_none_for_blank_query():
    conn = FakeConnection(fetch_results=[("아무거나",)])
    assert find_english_name(conn, "   ") is None


def test_article_exists_true_when_row_found():
    conn = FakeConnection(fetch_results=[(1,)])
    assert article_exists(conn, "https://wine21.com/1") is True


def test_article_exists_false_when_no_row():
    conn = FakeConnection(fetch_results=[])
    assert article_exists(conn, "https://wine21.com/1") is False


def test_get_article_returns_stored_fields_when_found():
    conn = FakeConnection(fetch_results=[("제목", "요약", "https://x/y.jpg", "2026-07-01")])
    assert get_article(conn, "https://wine21.com/1") == {
        "title": "제목", "excerpt": "요약", "thumbnail_url": "https://x/y.jpg", "published_date": "2026-07-01",
    }


def test_get_article_returns_none_when_no_row():
    conn = FakeConnection(fetch_results=[])
    assert get_article(conn, "https://wine21.com/1") is None


def test_insert_article_writes_article_and_brand_rows():
    conn = FakeConnection()
    article = ParsedArticle(
        title="제목", excerpt="요약", thumbnail_url="https://x/y.jpg", published_date="2026-07-01"
    )
    article_id = insert_article(conn, "와인21", "https://wine21.com/1", article, ["Montes", "Kaiken"], "news")

    assert article_id == 42
    assert conn.committed is True
    queries = [sql for sql, _ in conn.cursor().executed]
    assert any("INSERT INTO wine_articles" in q for q in queries)
    assert sum("INSERT INTO wine_article_brands" in q for q in queries) == 2


def test_insert_article_with_no_matched_brands():
    conn = FakeConnection()
    article = ParsedArticle(
        title="제목", excerpt="요약", thumbnail_url="https://x/y.jpg", published_date="2026-07-01"
    )
    article_id = insert_article(conn, "와인21", "https://wine21.com/1", article, [], "news")

    assert article_id == 42
    assert conn.committed is True
    queries = [sql for sql, _ in conn.cursor().executed]
    assert sum("INSERT INTO wine_articles" in q for q in queries) == 1
    assert sum("INSERT INTO wine_article_brands" in q for q in queries) == 0


def test_insert_article_rolls_back_on_failure():
    # First execute() (the wine_articles INSERT) succeeds; the second execute()
    # (the first wine_article_brands INSERT) raises, simulating a mid-loop failure.
    conn = FakeConnection(fail_after_n_executes=1)
    article = ParsedArticle(
        title="제목", excerpt="요약", thumbnail_url="https://x/y.jpg", published_date="2026-07-01"
    )

    with pytest.raises(RuntimeError, match="simulated execute failure"):
        insert_article(conn, "와인21", "https://wine21.com/1", article, ["Montes", "Kaiken"], "news")

    assert conn.rolled_back is True
    assert conn.committed is False


def test_insert_article_stores_source_category_in_sql():
    conn = FakeConnection()
    article = ParsedArticle(
        title="제목", excerpt="요약", thumbnail_url="https://x/y.jpg", published_date="2026-07-01"
    )
    insert_article(conn, "와인21", "https://wine21.com/1", article, [], "youtube")

    article_sql = next(sql for sql, _ in conn.cursor().executed if "INSERT INTO wine_articles" in sql)
    assert "source_category" in article_sql


def test_insert_article_passes_category_value_as_param():
    conn = FakeConnection()
    article = ParsedArticle(
        title="제목", excerpt="요약", thumbnail_url="https://x/y.jpg", published_date="2026-07-01"
    )
    insert_article(conn, "와인21", "https://wine21.com/1", article, [], "wassap")

    _, params = next((sql, p) for sql, p in conn.cursor().executed if "INSERT INTO wine_articles" in sql)
    assert "wassap" in params


def test_ensure_channel_prices_table_issues_create_table_if_not_exists():
    conn = FakeConnection()
    ensure_channel_prices_table(conn)
    assert "CREATE TABLE IF NOT EXISTS wine_channel_prices" in conn._cursor.executed[0][0]
    assert conn.committed


def test_insert_channel_price_inserts_one_row():
    conn = FakeConnection()
    row_id = insert_channel_price(
        conn, wine_query="몬테스 알파", channel="이마트", price_low=29800, price_high=33000,
        year_month="2026-07", source_type="blog", source_url="https://blog.naver.com/x/1",
    )
    assert row_id == 42  # FakeCursor 기본 lastrowid
    insert_sql, params = conn._cursor.executed[-1]
    assert "INSERT INTO wine_channel_prices" in insert_sql
    assert params == ("몬테스 알파", "이마트", 29800, 33000, "2026-07", "blog", "https://blog.naver.com/x/1")
    assert conn.committed
