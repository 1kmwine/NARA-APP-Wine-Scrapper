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
    """brandName(와이너리/생산자명, 예: "Jules Taylor")뿐 아니라 nameKo/nameEn
    (제품명, 예: "더 베터 하프 말보로 소비뇽 블랑"/"The Better half...")도 합친다 —
    브랜드명만으로는 사용자가 실제로 검색하는 "와인 이름"(생산자 아래 특정
    큐베/제품명)을 하나도 인식하지 못했다(2026-07-22 "베러하프" 검색 중 발견 —
    브랜드명 컬럼엔 이 이름이 아예 없어서 match_brands가 항상 빈 리스트를 반환)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT name FROM (
                SELECT brandName AS name FROM integrated_item_info WHERE brandName IS NOT NULL AND brandName != ''
                UNION
                SELECT nameKo AS name FROM integrated_item_info WHERE nameKo IS NOT NULL AND nameKo != ''
                UNION
                SELECT nameEn AS name FROM integrated_item_info WHERE nameEn IS NOT NULL AND nameEn != ''
            ) AS combined
            """
        )
        return [row[0] for row in cur.fetchall()]


def find_english_name(conn, query: str) -> str | None:
    """뉴스 검색어를 영문으로도 확장하기 위해, 사용자가 입력한 한글 와인명이
    nameKo와 (공백 유무 빼고) 일치하는 제품을 찾아 그 nameEn을 돌려준다.
    네이버 뉴스/블로그 검색은 한국어 콘텐츠 위주라 영문 표기만 쓰는 기사는
    한글 검색어로는 안 잡힌다."""
    normalized = query.replace(" ", "")
    if not normalized:
        return None
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT nameEn FROM integrated_item_info
            WHERE REPLACE(nameKo, ' ', '') LIKE CONCAT('%%', %s, '%%')
              AND nameEn IS NOT NULL AND nameEn != ''
            LIMIT 1
            """,
            (normalized,),
        )
        row = cur.fetchone()
        return row[0] if row else None


def article_exists(conn, external_url: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM wine_articles WHERE source_type = 'scraper' AND external_url = %s",
            (external_url,),
        )
        return cur.fetchone() is not None


def get_article(conn, external_url: str) -> dict | None:
    """중복 처리 시 기존에 저장된 title/excerpt를 재사용하기 위한 조회 —
    없으면 결과 카드에 raw URL이 제목으로 그대로 노출된다."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT title, excerpt, thumbnail_path, published_date FROM wine_articles "
            "WHERE source_type = 'scraper' AND external_url = %s",
            (external_url,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        title, excerpt, thumbnail_path, published_date = row
        if hasattr(published_date, "isoformat"):
            published_date = published_date.isoformat()
        return {"title": title, "excerpt": excerpt, "thumbnail_url": thumbnail_path, "published_date": published_date}


def insert_article(
    conn, source_name: str, external_url: str, article: ParsedArticle,
    matched_brands: list[str], source_category: str,
) -> int:
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO wine_articles
                    (source_type, source_category, title, source_name, published_date, external_url, thumbnail_path, excerpt)
                VALUES ('scraper', %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    source_category,
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


def ensure_channel_prices_table(conn) -> None:
    """마이그레이션 도구 없이(기존 관례) 매 insert 전에 idempotent하게 보장한다."""
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS wine_channel_prices (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                wine_query VARCHAR(255) NOT NULL,
                channel VARCHAR(50) NOT NULL,
                price_low INT NOT NULL,
                price_high INT NOT NULL,
                year_month CHAR(7) NOT NULL,
                source_type VARCHAR(20) NOT NULL,
                source_url VARCHAR(500) NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_wine_channel_month (wine_query, channel, year_month)
            )
            """
        )
    conn.commit()


def insert_channel_price(
    conn, wine_query: str, channel: str, price_low: int, price_high: int,
    year_month: str, source_type: str, source_url: str,
) -> int:
    ensure_channel_prices_table(conn)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO wine_channel_prices
                (wine_query, channel, price_low, price_high, year_month, source_type, source_url)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (wine_query, channel, price_low, price_high, year_month, source_type, source_url),
        )
        row_id = cur.lastrowid
    conn.commit()
    return row_id
