from __future__ import annotations
import pymysql

from .parse import ParsedArticle


def get_connection(host: str, port: int, user: str, password: str, database: str):
    return pymysql.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
        charset="utf8mb4",
        autocommit=False,
    )


def get_known_brands(conn) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT brandName FROM integrated_item_info "
            "WHERE brandName IS NOT NULL AND brandName != ''"
        )
        return [row[0] for row in cur.fetchall()]


def article_exists(conn, external_url: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM wine_articles WHERE source_type = 'scraper' AND external_url = %s",
            (external_url,),
        )
        return cur.fetchone() is not None


def insert_article(
    conn, source_name: str, external_url: str, article: ParsedArticle, matched_brands: list[str]
) -> int:
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO wine_articles
                    (source_type, title, source_name, published_date, external_url, thumbnail_path, excerpt)
                VALUES ('scraper', %s, %s, %s, %s, %s, %s)
                """,
                (
                    article.title,
                    source_name,
                    article.published_date,
                    external_url,
                    article.thumbnail_url,
                    article.excerpt,
                ),
            )
            article_id = cur.lastrowid
            for brand_name in matched_brands:
                cur.execute(
                    "INSERT INTO wine_article_brands (article_id, brand_name) VALUES (%s, %s)",
                    (article_id, brand_name),
                )
    except Exception:
        conn.rollback()
        raise
    conn.commit()
    return article_id
