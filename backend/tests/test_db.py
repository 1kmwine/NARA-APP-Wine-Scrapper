import pytest

from app.db import get_known_brands, article_exists, insert_article
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


def test_insert_article_with_no_matched_brands():
    conn = FakeConnection()
    article = ParsedArticle(
        title="제목", excerpt="요약", thumbnail_url="https://x/y.jpg", published_date="2026-07-01"
    )
    article_id = insert_article(conn, "와인21", "https://wine21.com/1", article, [])

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
        insert_article(conn, "와인21", "https://wine21.com/1", article, ["Montes", "Kaiken"])

    assert conn.rolled_back is True
    assert conn.committed is False
