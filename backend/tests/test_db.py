from app.db import get_known_brands, article_exists, insert_article
from app.parse import ParsedArticle


class FakeCursor:
    def __init__(self, fetch_results=None):
        self.executed = []
        self._fetch_results = fetch_results or []
        self.lastrowid = 42

    def execute(self, sql, params=None):
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
    def __init__(self, fetch_results=None):
        self._cursor = FakeCursor(fetch_results)
        self.committed = False

    def cursor(self):
        return self._cursor

    def commit(self):
        self.committed = True


def test_get_known_brands_returns_distinct_names():
    conn = FakeConnection(fetch_results=[("Montes",), ("Kaiken",)])
    assert get_known_brands(conn) == ["Montes", "Kaiken"]


def test_article_exists_true_when_row_found():
    conn = FakeConnection(fetch_results=[(1,)])
    assert article_exists(conn, "https://wine21.com/1") is True


def test_article_exists_false_when_no_row():
    conn = FakeConnection(fetch_results=[])
    assert article_exists(conn, "https://wine21.com/1") is False


def test_insert_article_writes_article_and_brand_rows():
    conn = FakeConnection()
    article = ParsedArticle(
        title="제목", excerpt="요약", thumbnail_url="https://x/y.jpg", published_date="2026-07-01"
    )
    article_id = insert_article(conn, "와인21", "https://wine21.com/1", article, ["Montes", "Kaiken"])

    assert article_id == 42
    assert conn.committed is True
    queries = [sql for sql, _ in conn.cursor().executed]
    assert any("INSERT INTO wine_articles" in q for q in queries)
    assert sum("INSERT INTO wine_article_brands" in q for q in queries) == 2
