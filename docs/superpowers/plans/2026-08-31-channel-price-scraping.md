# a5 채널별 가격 수집 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a5 온디맨드 검색에서 블로그·와쌉카페 게시글 본문을 수집해 채널별 가격을
정규식으로 추출하고, DB에 소스 단위로 저장한 뒤, 검색 결과 화면에 뉴스·매거진과
블로그 사이 "가격" 표로 보여준다.

**Architecture:** `run_job()`이 기존 블로그/와쌉 수집 직후 각 게시글의 본문 전체를
새로 가져와(`fetch_blog_full_body`/`fetch_wassap_full_body`) `extract_channel_prices()`로
정규식 매칭한 뒤 `wine_channel_prices` DB에 건별로 INSERT하고, 이번 검색에서 찾은
것만 채널별로 min~max 병합해 `GET /jobs/{id}` 응답의 새 필드 `price_results`로
반환한다. 프론트는 그 필드를 표로 렌더링한다.

**Tech Stack:** 기존 스택 그대로 — FastAPI(`backend/app/`), pymysql, httpx, 순수
JS(`js/app.js`), 정규식(신규 의존성 없음).

**Spec:** `docs/superpowers/specs/2026-08-31-channel-price-scraping-design.md`

## Global Constraints

- 가격 추출은 정규식 패턴 매칭만 사용한다(LLM 미사용).
- 본문 텍스트(se-text)에 직접 타이핑된 가격만 대상 — 위젯/이미지 안의 가격은
  범위 밖.
- DB 테이블 `wine_channel_prices`: 한 소스에서 채취한 가격 = 한 행(병합 없음).
  컬럼: `id, wine_query, channel, price_low, price_high, year_month(CHAR(7)),
  source_type, source_url, created_at`.
- 화면에는 **이번 검색에서 새로 찾은 것만** 표시(과거 DB 누적분 조회 UI는 범위 밖).
- 같은 채널을 여러 소스가 언급하면 화면 표시는 min~max 범위로 병합하고, 출처
  링크는 전부 나열한다. 병합된 year_month가 소스마다 다르면 가장 최근 값을 쓴다.
- 채널에 값이 없으면 표에서 그 행 자체를 생략한다.
- 채널 정식 명칭 14개: 이마트, 코스트코, 트레이더스, 롯데마트, CU, GS25, 이마트24,
  세븐일레븐, 새마을구판장, 조양마트, 레드셀러, 와인픽스, 에노테카, 와인앤모어.
- 와쌉 게시글 상세 엔드포인트(2026-08-31 실측 확인):
  `GET https://article.cafe.naver.com/gw/v4/cafes/{cafe_numeric_id}/articles/{article_id}?query=&fromPopular=true&useCafeId=true&requestFrom=A`
  → 응답 `result.article.contentHtml`에 Smart Editor HTML 본문.
- DB 접속: `backend/.env`의 `DB_ID_MARKETING` 계정(2026-08-31 갱신 완료, `wine_info`
  스키마 ALL PRIVILEGES 확인됨) — 이 계정으로 실제 DB 접속·테이블 생성 가능.

---

### Task 1: `price_extraction.py` — 채널 별칭 + 정규식 추출 + 화면 병합

순수 로직, 네트워크 없음. TDD로 처음부터 만든다.

**Files:**
- Create: `backend/app/price_extraction.py`
- Test: `backend/tests/test_price_extraction.py`

**Interfaces:**
- Produces:
  - `CHANNEL_ALIASES: dict[str, list[str]]` — 정식 채널명 → 별칭 리스트, 순서 있음(딕셔너리 순회 순서 그대로 매칭 우선순위)
  - `extract_channel_prices(body_text: str, fallback_year_month: str) -> list[dict]` — 각 dict는 `{"channel": str, "price_low": int, "price_high": int, "year_month": str}`
  - `merge_channel_prices_for_display(rows: list[dict]) -> list[dict]` — 입력 각 dict는 `{"channel", "price_low", "price_high", "year_month", "source_url"}`, 출력 각 dict는 `{"channel", "price_low", "price_high", "year_month", "source_urls": list[str]}`, 채널당 최대 1개, 채널별로 정식 순서(CHANNEL_ALIASES 키 순서) 정렬

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_price_extraction.py`:

```python
from app.price_extraction import extract_channel_prices, merge_channel_prices_for_display


def test_extracts_single_price_with_explicit_month():
    text = "이마트 7월 29,800원에 샀어요 개꿀"
    result = extract_channel_prices(text, fallback_year_month="2026-01")
    assert result == [{"channel": "이마트", "price_low": 29800, "price_high": 29800, "year_month": "2026-07"}]


def test_extracts_price_range():
    text = "이마트 매장마다 다른데 29,800원~33,000원 정도 하더라구요"
    result = extract_channel_prices(text, fallback_year_month="2026-07")
    assert result == [{"channel": "이마트", "price_low": 29800, "price_high": 33000, "year_month": "2026-07"}]


def test_falls_back_to_post_year_month_when_no_month_mentioned():
    text = "코스트코 19,900원 완전 혜자"
    result = extract_channel_prices(text, fallback_year_month="2026-05")
    assert result == [{"channel": "코스트코", "price_low": 19900, "price_high": 19900, "year_month": "2026-05"}]


def test_emart24_not_misdetected_as_plain_emart():
    text = "이마트24 앱으로 21,000원에 픽업했어요"
    result = extract_channel_prices(text, fallback_year_month="2026-07")
    assert result == [{"channel": "이마트24", "price_low": 21000, "price_high": 21000, "year_month": "2026-07"}]


def test_plain_emart_still_detected_when_not_followed_by_24():
    text = "이마트 가서 29,800원 주고 샀어요"
    result = extract_channel_prices(text, fallback_year_month="2026-07")
    assert result == [{"channel": "이마트", "price_low": 29800, "price_high": 29800, "year_month": "2026-07"}]


def test_multiple_channels_in_one_post():
    text = "이마트 29,800원\n코스트코 25,000원"
    result = extract_channel_prices(text, fallback_year_month="2026-07")
    assert result == [
        {"channel": "이마트", "price_low": 29800, "price_high": 29800, "year_month": "2026-07"},
        {"channel": "코스트코", "price_low": 25000, "price_high": 25000, "year_month": "2026-07"},
    ]


def test_no_channel_or_price_returns_empty_list():
    assert extract_channel_prices("오늘 저녁은 파스타 먹었어요", fallback_year_month="2026-07") == []
    assert extract_channel_prices("이마트 다녀왔어요 좋더라구요", fallback_year_month="2026-07") == []  # 채널만 있고 가격 없음


def test_merge_combines_multiple_sources_into_range():
    rows = [
        {"channel": "이마트", "price_low": 29800, "price_high": 29800, "year_month": "2026-07", "source_url": "https://a"},
        {"channel": "이마트", "price_low": 31000, "price_high": 31000, "year_month": "2026-07", "source_url": "https://b"},
    ]
    merged = merge_channel_prices_for_display(rows)
    assert merged == [{
        "channel": "이마트", "price_low": 29800, "price_high": 31000, "year_month": "2026-07",
        "source_urls": ["https://a", "https://b"],
    }]


def test_merge_uses_most_recent_year_month_when_sources_disagree():
    rows = [
        {"channel": "이마트", "price_low": 29800, "price_high": 29800, "year_month": "2026-05", "source_url": "https://a"},
        {"channel": "이마트", "price_low": 31000, "price_high": 31000, "year_month": "2026-07", "source_url": "https://b"},
    ]
    merged = merge_channel_prices_for_display(rows)
    assert merged[0]["year_month"] == "2026-07"


def test_merge_sorts_by_canonical_channel_order():
    rows = [
        {"channel": "코스트코", "price_low": 1, "price_high": 1, "year_month": "2026-07", "source_url": "https://a"},
        {"channel": "이마트", "price_low": 2, "price_high": 2, "year_month": "2026-07", "source_url": "https://b"},
    ]
    merged = merge_channel_prices_for_display(rows)
    assert [r["channel"] for r in merged] == ["이마트", "코스트코"]  # CHANNEL_ALIASES 순서: 이마트24, 이마트, 코스트코...
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd backend && .venv/bin/python3 -m pytest tests/test_price_extraction.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.price_extraction'`

- [ ] **Step 3: 최소 구현 작성**

`backend/app/price_extraction.py`:

```python
from __future__ import annotations
import re
from datetime import date

# 순서가 매칭 우선순위다 — "이마트24"를 "이마트"보다 먼저 둬서, 아래 CHANNEL 매칭
# 루프가 "이마트24"를 먼저 확정하면 그 라인에서 "이마트"(plain)는 negative
# lookahead로 걸러진다(둘 다 매칭되는 이중 카운트 방지).
CHANNEL_ALIASES: dict[str, list[str]] = {
    "이마트24": ["이마트24", "이마트 24", "E24", "e24"],
    "이마트": ["이마트몰", "이마트(?!\\s*24)"],
    "코스트코": ["코스트코 홀세일", "코스트코"],
    "트레이더스": ["트레이더스 홀세일", "트레이더스"],
    "롯데마트": ["롯데마트"],
    "CU": ["(?<![A-Za-z])CU(?![A-Za-z])", "씨유"],
    "GS25": ["GS25", "지에스\\s*25"],
    "세븐일레븐": ["세븐일레븐24", "세븐일레븐앱", "세븐일레븐", "7-11"],
    "새마을구판장": ["새마을\\s*구판장"],
    "조양마트": ["조양마트"],
    "레드셀러": ["레드셀러"],
    "와인픽스": ["와인픽스"],
    "에노테카": ["에노테카"],
    "와인앤모어": ["와인\\s*앤\\s*모어"],
}

_CHANNEL_ORDER = list(CHANNEL_ALIASES.keys())
_CHANNEL_PATTERNS = {
    channel: re.compile("|".join(aliases))
    for channel, aliases in CHANNEL_ALIASES.items()
}

# 콤마 그룹(예: 29,800) 또는 4~6자리 순수 숫자(예: 29800) + "원"
_PRICE_RE = re.compile(r'(\d{1,3}(?:,\d{3})+|\d{4,6})\s*원')
_MONTH_RE = re.compile(r'(\d{1,2})\s*월')


def _resolve_year_month(line: str, fallback_year_month: str) -> str:
    match = _MONTH_RE.search(line)
    if not match:
        return fallback_year_month
    month = int(match.group(1))
    if not 1 <= month <= 12:
        return fallback_year_month
    today = date.today()
    year = today.year if month <= today.month else today.year - 1
    return f"{year:04d}-{month:02d}"


def extract_channel_prices(body_text: str, fallback_year_month: str) -> list[dict]:
    """정규식 기반 휴리스틱 — 본문에 직접 타이핑된 채널명+가격만 잡는다.
    위젯/이미지 안의 가격, 표현이 크게 다른 문장은 놓칠 수 있음(지어내지 않음:
    채널명과 가격 패턴이 같은 줄에서 둘 다 확인될 때만 결과에 넣는다)."""
    results: list[dict] = []
    for line in body_text.splitlines():
        if not line.strip():
            continue
        prices = [int(p.replace(",", "")) for p in _PRICE_RE.findall(line)]
        if not prices:
            continue
        for channel, pattern in _CHANNEL_PATTERNS.items():
            if not pattern.search(line):
                continue
            results.append({
                "channel": channel,
                "price_low": min(prices),
                "price_high": max(prices),
                "year_month": _resolve_year_month(line, fallback_year_month),
            })
    return results


def merge_channel_prices_for_display(rows: list[dict]) -> list[dict]:
    """채널별로 min~max 병합, 출처는 전부 나열, year_month는 가장 최근 값 사용.
    반환 순서는 CHANNEL_ALIASES 정의 순서를 따른다."""
    by_channel: dict[str, dict] = {}
    for row in rows:
        channel = row["channel"]
        entry = by_channel.get(channel)
        if entry is None:
            by_channel[channel] = {
                "channel": channel,
                "price_low": row["price_low"],
                "price_high": row["price_high"],
                "year_month": row["year_month"],
                "source_urls": [row["source_url"]],
            }
        else:
            entry["price_low"] = min(entry["price_low"], row["price_low"])
            entry["price_high"] = max(entry["price_high"], row["price_high"])
            if row["year_month"] > entry["year_month"]:
                entry["year_month"] = row["year_month"]
            entry["source_urls"].append(row["source_url"])
    return [by_channel[c] for c in _CHANNEL_ORDER if c in by_channel]
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd backend && .venv/bin/python3 -m pytest tests/test_price_extraction.py -v`
Expected: PASS (11 tests)

- [ ] **Step 5: 커밋**

```bash
git add backend/app/price_extraction.py backend/tests/test_price_extraction.py
git commit -m "feat: 채널별 가격 정규식 추출/병합 로직 추가"
```

---

### Task 2: DB 레이어 — `wine_channel_prices` 테이블 생성 + INSERT

**Files:**
- Modify: `backend/app/db.py`
- Test: `backend/tests/test_db.py`

**Interfaces:**
- Consumes: (없음)
- Produces:
  - `ensure_channel_prices_table(conn) -> None`
  - `insert_channel_price(conn, wine_query: str, channel: str, price_low: int, price_high: int, year_month: str, source_type: str, source_url: str) -> int` (반환값은 lastrowid)

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_db.py`에 추가(기존 `FakeCursor`/`FakeConnection` 재사용):

```python
from app.db import ensure_channel_prices_table, insert_channel_price


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
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd backend && .venv/bin/python3 -m pytest tests/test_db.py -v -k channel_price`
Expected: FAIL — `ImportError: cannot import name 'ensure_channel_prices_table'`

- [ ] **Step 3: 최소 구현 작성**

`backend/app/db.py`에 추가:

```python
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
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd backend && .venv/bin/python3 -m pytest tests/test_db.py -v -k channel_price`
Expected: PASS (2 tests)

- [ ] **Step 5: 실제 DB로 라이브 스모크 테스트 (1회, 수동)**

`backend/.env`의 `DB_ID_MARKETING` 계정으로 실제 테이블 생성 + INSERT + SELECT까지
확인한다(2026-08-31에 이 계정으로 `wine_info` 스키마 ALL PRIVILEGES 확인됨):

```bash
cd backend && .venv/bin/python3 -c "
from app.config import get_settings
from app.db import get_connection, insert_channel_price
s = get_settings()
conn = get_connection(s.db_host, s.db_port, s.db_username, s.db_password, s.db_database)
row_id = insert_channel_price(conn, '__plan_test__', '이마트', 29800, 33000, '2026-07', 'blog', 'https://example.com/test')
print('inserted row_id:', row_id)
with conn.cursor() as cur:
    cur.execute('SELECT * FROM wine_channel_prices WHERE wine_query = %s', ('__plan_test__',))
    print(cur.fetchall())
    cur.execute('DELETE FROM wine_channel_prices WHERE wine_query = %s', ('__plan_test__',))
conn.commit()
conn.close()
"
```

Expected: `inserted row_id: <숫자>` 출력, SELECT 결과에 방금 넣은 행이 실제로 보임,
마지막 DELETE로 테스트 행 정리(실 DB에 테스트 데이터 남기지 않음).

- [ ] **Step 6: 커밋**

```bash
git add backend/app/db.py backend/tests/test_db.py
git commit -m "feat: wine_channel_prices 테이블 생성/INSERT 함수 추가"
```

---

### Task 3: 게시글 본문 전체 가져오기 (블로그 모바일 URL / 와쌉 게시글 상세 API)

**Files:**
- Modify: `backend/app/collectors.py`
- Test: `backend/tests/test_collectors.py`

**Interfaces:**
- Consumes: `_BLOG_LINK_RE`(기존, `collectors.py`에 이미 정의됨)
- Produces:
  - `fetch_blog_full_body(external_url: str, client) -> str | None`
  - `fetch_wassap_full_body(cafe_numeric_id: str, external_url: str, client, naver_cookie: str) -> str | None`

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_collectors.py`에 추가:

```python
from app.collectors import fetch_blog_full_body, fetch_wassap_full_body


class FakeMobileBlogResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


class FakeMobileBlogClient:
    def __init__(self, html_by_key):
        self._html = html_by_key

    def get(self, url, timeout=None):
        assert "m.blog.naver.com/" in url
        key = url.split("m.blog.naver.com/")[1]
        return FakeMobileBlogResponse(self._html.get(key, "<html></html>"))


def test_fetch_blog_full_body_uses_mobile_url_and_strips_tags():
    client = FakeMobileBlogClient({
        "naracellar/224352889386": "<p>이마트 7월 29,800원~33,000원 정도</p><br><p>완전 혜자</p>",
    })

    body = fetch_blog_full_body("https://blog.naver.com/naracellar/224352889386", client)

    assert body == "이마트 7월 29,800원~33,000원 정도\n완전 혜자"


def test_fetch_blog_full_body_returns_none_on_unparseable_url():
    assert fetch_blog_full_body("https://example.com/not-a-blog-link", FakeMobileBlogClient({})) is None


def test_fetch_blog_full_body_returns_none_on_fetch_failure():
    class BrokenClient:
        def get(self, url, timeout=None):
            raise RuntimeError("network down")

    assert fetch_blog_full_body("https://blog.naver.com/x/1", BrokenClient()) is None


class FakeArticleDetailResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class FakeArticleDetailClient:
    def __init__(self, payload):
        self._payload = payload
        self.last_call = None

    def get(self, url, *, params=None, headers=None, timeout=None):
        assert "article.cafe.naver.com/gw/v4/cafes/20564405/articles/369628" in url
        self.last_call = {"url": url, "params": params, "headers": headers}
        return FakeArticleDetailResponse(self._payload)


ARTICLE_DETAIL_PAYLOAD = {
    "result": {"article": {"contentHtml": "<p>CU 21,000원에 픽업했어요</p>"}}
}


def test_fetch_wassap_full_body_calls_article_detail_endpoint():
    client = FakeArticleDetailClient(ARTICLE_DETAIL_PAYLOAD)

    body = fetch_wassap_full_body("20564405", "https://cafe.naver.com/winerack24/369628", client, naver_cookie="fake-cookie")

    assert body == "CU 21,000원에 픽업했어요"
    assert client.last_call["headers"]["Cookie"] == "fake-cookie"


def test_fetch_wassap_full_body_returns_none_on_unparseable_url():
    client = FakeArticleDetailClient(ARTICLE_DETAIL_PAYLOAD)
    assert fetch_wassap_full_body("20564405", "https://example.com/not-cafe", client, naver_cookie="x") is None


def test_fetch_wassap_full_body_returns_none_on_fetch_failure():
    class BrokenClient:
        def get(self, url, *, params=None, headers=None, timeout=None):
            raise RuntimeError("network down")

    body = fetch_wassap_full_body("20564405", "https://cafe.naver.com/winerack24/369628", BrokenClient(), naver_cookie="x")
    assert body is None
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd backend && .venv/bin/python3 -m pytest tests/test_collectors.py -v -k full_body`
Expected: FAIL — `ImportError: cannot import name 'fetch_blog_full_body'`

- [ ] **Step 3: 최소 구현 작성**

`backend/app/collectors.py`에 추가(파일 상단 `import` 구역에 `import html as html_module` 추가 필요 — 이미 있는 `import re`/`import json`은 재사용):

```python
_BLOCK_BREAK_RE = re.compile(r'</p>|<br\s*/?>|</div>', re.IGNORECASE)
_TAG_RE = re.compile(r'<[^>]+>')


def _html_to_lines(html_str: str) -> str:
    """블록 태그(</p>, <br>, </div>)를 줄바꿈으로 바꾼 뒤 나머지 태그를 벗기고
    HTML 엔티티(&#x3D; 등, Smart Editor 콘텐츠에 흔함)를 복원한다. 빈 줄은 버린다."""
    text = _BLOCK_BREAK_RE.sub('\n', html_str)
    text = _TAG_RE.sub('', text)
    text = html_module.unescape(text)
    lines = [ln.strip() for ln in text.split('\n')]
    return '\n'.join(ln for ln in lines if ln)


def fetch_blog_full_body(external_url: str, client) -> str | None:
    """검색 스니펫(description)만으론 본문 속 가격 언급을 못 잡는다. m.blog.naver.com은
    PC용 PostView.naver(iframe 껍데기, og:image만 있음)와 달리 본문을 서버에서
    직접 렌더링해준다."""
    match = _BLOG_LINK_RE.search(external_url)
    if not match:
        return None
    blog_id, log_no = match.groups()
    try:
        response = client.get(f"https://m.blog.naver.com/{blog_id}/{log_no}", timeout=10.0)
        response.raise_for_status()
        return _html_to_lines(response.text)
    except Exception:  # noqa: BLE001 — 이 게시글만 스킵, 전체 검색은 계속
        return None


_ARTICLE_ID_RE = re.compile(r'cafe\.naver\.com/[\w-]+/(\d+)')


def fetch_wassap_full_body(cafe_numeric_id: str, external_url: str, client, naver_cookie: str) -> str | None:
    """search_wassap()의 summary(150자 스니펫)만으론 본문 속 가격 언급을 못 잡는다.
    게시글 상세 API(2026-08-31 devtools로 실측 확인)로 본문 전체(contentHtml)를
    가져온다. CU픽업주문 위젯/이미지 안의 가격은 이 방식으로도 못 잡음(정규식
    범위 밖, se-text 문단 텍스트만 대상)."""
    match = _ARTICLE_ID_RE.search(external_url)
    if not match:
        return None
    article_id = match.group(1)
    headers = {
        "Cookie": naver_cookie,
        "Referer": external_url,
        "Origin": "https://cafe.naver.com",
        "Accept": "application/json, text/plain, */*",
        "User-Agent": "Mozilla/5.0",
        "X-Cafe-Product": "pc",
        "X-Cafe-Version": "1.0",
        "X-Cafe-Phase": "real",
    }
    try:
        response = client.get(
            f"https://article.cafe.naver.com/gw/v4/cafes/{cafe_numeric_id}/articles/{article_id}",
            params={"query": "", "fromPopular": "true", "useCafeId": "true", "requestFrom": "A"},
            headers=headers, timeout=15.0,
        )
        response.raise_for_status()
        content_html = response.json().get("result", {}).get("article", {}).get("contentHtml") or ""
        return _html_to_lines(content_html) or None
    except Exception:  # noqa: BLE001 — 이 게시글만 스킵, 전체 검색은 계속
        return None
```

Also add `import html as html_module` near the top of `backend/app/collectors.py` (alongside the existing `import json`/`import re`).

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd backend && .venv/bin/python3 -m pytest tests/test_collectors.py -v -k full_body`
Expected: PASS (6 tests)

- [ ] **Step 5: 실제 네이버 서버로 라이브 스모크 테스트 (1회, 수동)**

이 함수들은 실제 네이버 페이지 구조에 의존한다 — 배포 전 실제 호출로 확인:

```bash
cd backend && .venv/bin/python3 -c "
import httpx
from app.config import get_settings
from app.collectors import fetch_wassap_full_body, fetch_blog_full_body
s = get_settings()
with httpx.Client(follow_redirects=True, timeout=15.0) as client:
    body = fetch_wassap_full_body('20564405', 'https://cafe.naver.com/winerack24/369628', client, s.naver_cookie)
    print('와쌉 본문 길이:', len(body) if body else None)
    print(body[:200] if body else '(실패)')
"
```

Expected: 본문 텍스트가 실제로 나옴(빈 값이나 예외가 아니라 "저도 CU 딸보 동참" 관련
텍스트가 보여야 함 — 이 게시글은 2026-08-31에 이미 존재 확인됨). 블로그 쪽은 검색
결과에서 실제 `external_url` 하나를 골라 같은 방식으로 확인한다.

- [ ] **Step 6: 커밋**

```bash
git add backend/app/collectors.py backend/tests/test_collectors.py
git commit -m "feat: 블로그/와쌉 게시글 본문 전체 가져오기 추가"
```

---

### Task 4: `run_job()` 통합 — 가격 추출/저장/응답 반영

**Files:**
- Modify: `backend/app/jobs.py`
- Test: `backend/tests/test_jobs.py`

**Interfaces:**
- Consumes: `extract_channel_prices`, `merge_channel_prices_for_display` (Task 1),
  `CollectedItem` (기존)
- Produces: `Job.price_results: list[dict]` (신규 필드), `run_job()`의 신규 파라미터
  `fetch_blog_body: Callable[[str], Optional[str]]`,
  `fetch_wassap_body: Callable[[object, str], Optional[str]]`,
  `insert_channel_price: Callable[[str, str, int, int, str, str, str], int]`

- [ ] **Step 1: `Job`에 `price_results` 필드 추가**

`backend/app/jobs.py`의 `Job` dataclass(17번째 줄 부근)에 추가:

```python
@dataclass
class Job:
    id: str
    wine_name: str
    brand: str
    status: str = "pending"
    total: int = 0
    done: int = 0
    results: list[JobResultItem] = field(default_factory=list)
    price_results: list[dict] = field(default_factory=list)
    error: Optional[str] = None
```

- [ ] **Step 2: 기존 테스트가 여전히 통과하는지 확인(회귀 확인)**

Run: `cd backend && .venv/bin/python3 -m pytest tests/test_jobs.py tests/test_main.py -v`
Expected: PASS (필드 추가만으론 기존 동작 안 깨짐 — `default_factory`라 기존
`Job(...)` 생성 호출들이 그대로 동작)

- [ ] **Step 3: 실패하는 테스트 작성 (가격 추출 통합)**

`backend/tests/test_jobs.py`의 `_news_deps()` 헬퍼(28번째 줄 부근)에 새 기본값
3개를 추가(다른 테스트가 이 키들을 안 건드리면 "가격 없음"으로 동작해야 기존
테스트가 안 깨짐):

```python
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
        fetch_blog_body=lambda url: None,
        fetch_wassap_body=lambda source, url: None,
        insert_channel_price=lambda *a, **k: 1,
    )
    deps.update(overrides)
    return deps
```

파일 끝에 새 테스트 추가:

```python
def test_run_job_extracts_and_stores_blog_prices():
    store = JobStore()
    job = store.create("몬테스", "몬테스", total=1)
    sources = _empty_sources()
    inserted = []

    run_job(job.id, store, sources, "몬테스", "몬테스", **_news_deps(
        fetch_blog_items=lambda query: [CollectedItem(
            title="후기", excerpt="요약", thumbnail_url=None,
            external_url="https://blog.naver.com/naracellar/1", published_date="2026-06-15",
            source_name="블로그: 나라셀라",
        )],
        fetch_blog_body=lambda url: "이마트 29,800원~33,000원 완전 혜자",
        insert_channel_price=lambda *a, **k: inserted.append(a) or 1,
    ))

    result = store.get(job.id)
    assert result.price_results == [{
        "channel": "이마트", "price_low": 29800, "price_high": 33000,
        "year_month": "2026-06", "source_urls": ["https://blog.naver.com/naracellar/1"],
    }]
    assert len(inserted) == 1
    assert inserted[0][:2] == ("몬테스", "이마트")


def test_run_job_price_extraction_failure_does_not_fail_whole_job():
    store = JobStore()
    job = store.create("몬테스", "몬테스", total=1)
    sources = _empty_sources()

    def broken_fetch_blog_body(url):
        raise RuntimeError("network down")

    run_job(job.id, store, sources, "몬테스", "몬테스", **_news_deps(
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


def test_run_job_extracts_wassap_prices():
    store = JobStore()
    job = store.create("몬테스", "몬테스", total=1)
    wassap_source = WassapSource(
        id="winerack24-10050146", name="와쌉", cafe_id="winerack24", clubid="10050146",
        cafe_numeric_id="20564405",
    )
    sources = _empty_sources(wassap=[wassap_source])
    seen_args = []

    def fake_fetch_wassap_body(source, url):
        seen_args.append((source.cafe_numeric_id, url))
        return "CU 21,000원에 픽업했어요"

    run_job(job.id, store, sources, "몬테스", "몬테스", **_news_deps(
        fetch_wassap_items=lambda source: [CollectedItem(
            title="후기", excerpt="요약", thumbnail_url=None,
            external_url="https://cafe.naver.com/winerack24/369628", published_date="2026-08-31",
            source_name="와쌉",
        )],
        fetch_wassap_body=fake_fetch_wassap_body,
    ))

    result = store.get(job.id)
    assert result.price_results == [{
        "channel": "CU", "price_low": 21000, "price_high": 21000,
        "year_month": "2026-08", "source_urls": ["https://cafe.naver.com/winerack24/369628"],
    }]
    assert seen_args == [("20564405", "https://cafe.naver.com/winerack24/369628")]
```

- [ ] **Step 4: 테스트 실패 확인**

Run: `cd backend && .venv/bin/python3 -m pytest tests/test_jobs.py -v -k price`
Expected: FAIL — `TypeError: run_job() missing ... required positional argument: 'fetch_blog_body'` (또는 유사한 시그니처 불일치)

- [ ] **Step 5: 최소 구현 작성**

`backend/app/jobs.py` 상단 import에 추가:

```python
from datetime import datetime
from .price_extraction import extract_channel_prices, merge_channel_prices_for_display
```

`run_job()` 시그니처(약 214번째 줄)에 파라미터 3개 추가(기존 `fetch_international_items` 다음, `deadline` 앞):

```python
    fetch_international_items: Callable[[object], list[CollectedItem]],
    fetch_blog_body: Callable[[str], Optional[str]],
    fetch_wassap_body: Callable[[object, str], Optional[str]],
    insert_channel_price: Callable[[str, str, int, int, str, str, str], int],
    deadline: float | None = None,
) -> None:
```

`run_job()` 본문 맨 앞부분(`had_failure = False` 근처)에 누적 리스트 추가:

```python
    had_failure = False
    timed_out = False
    price_rows: list[dict] = []

    def _today_year_month() -> str:
        return datetime.now().strftime("%Y-%m")

    def _collect_prices(body_text: str | None, published_date: str | None, source_type: str, source_url: str) -> None:
        if not body_text:
            return
        fallback_ym = (published_date or "")[:7] or _today_year_month()
        try:
            for p in extract_channel_prices(body_text, fallback_ym):
                insert_channel_price(
                    query, p["channel"], p["price_low"], p["price_high"], p["year_month"],
                    source_type, source_url,
                )
                price_rows.append({**p, "source_url": source_url})
        except Exception:  # noqa: BLE001 — 가격 저장 실패는 이 소스만 생략, 검색 전체는 계속
            logger.exception("가격 저장 실패: %s", source_url)
```

기존 블로그 처리 루프(`for item in blog_items:` 안, `_process_collected_item` 호출
바로 다음 줄)에 한 줄 추가:

```python
            for item in blog_items:
                try:
                    _process_collected_item(
                        job_id, store, "naver-blog", "blog", item, known_brands, query,
                        get_existing_article, insert_article, match_brands,
                        skip_relevance_filter=True,
                    )
                except Exception as exc:  # noqa: BLE001
                    ...
                try:
                    _collect_prices(fetch_blog_body(item.external_url), item.published_date, "blog", item.external_url)
                except Exception:  # noqa: BLE001 — fetch_blog_body 자체가 예외를 던지는 극단적 경우 대비
                    logger.exception("블로그 본문 가져오기 실패: %s", item.external_url)
```

`category_sources` 루프(약 424번째 줄) 안, `for item in items:` 블록에서 `category == "wassap"`일 때만 실행되도록 한 줄 추가:

```python
            for item in items:
                try:
                    _process_collected_item(
                        job_id, store, source.id, category, item, known_brands, query,
                        get_existing_article, insert_article, match_brands,
                        trust_source=trust_source,
                    )
                except Exception as exc:  # noqa: BLE001
                    ...
                if category == "wassap":
                    try:
                        _collect_prices(fetch_wassap_body(source, item.external_url), item.published_date, "wassap", item.external_url)
                    except Exception:  # noqa: BLE001
                        logger.exception("와쌉 본문 가져오기 실패: %s", item.external_url)
```

`run_job()` 마지막(`store.update(job_id, status=...)` 직전)에 병합 결과 저장:

```python
    merged_prices = merge_channel_prices_for_display(price_rows)
    store.update(job_id, price_results=merged_prices)

    if timed_out:
        store.update(job_id, status="failed", error="60초 시간 제한을 초과했습니다")
    else:
        store.update(job_id, status="partial" if had_failure else "succeeded")
```

- [ ] **Step 6: 테스트 통과 확인**

Run: `cd backend && .venv/bin/python3 -m pytest tests/test_jobs.py tests/test_main.py -v`
Expected: PASS 전체(기존 테스트 포함 회귀 없음, 신규 3개 포함)

- [ ] **Step 7: 커밋**

```bash
git add backend/app/jobs.py backend/tests/test_jobs.py
git commit -m "feat: run_job에 채널별 가격 추출/저장 통합"
```

---

### Task 5: `main.py` 연결 — 실제 fetch 함수 배선 + API 응답 필드 추가

**Files:**
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_main.py`

**Interfaces:**
- Consumes: `run_job`의 신규 파라미터(Task 4), `db.insert_channel_price`(Task 2),
  `collectors.fetch_blog_full_body`/`fetch_wassap_full_body`(Task 3)
- Produces: `GET /jobs/{id}` 응답에 `price_results` 필드 추가

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_main.py`에 추가(기존 `test_create_job_and_poll_status` 아래):

```python
def test_get_job_includes_price_results(monkeypatch):
    monkeypatch.setattr(main_module.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(main_module, "_load_current_sources", lambda: _one_news_source_config())

    def fake_run_job(job_id, store, sources, wine_name, brand, **deps):
        store.update(
            job_id, status="succeeded", done=sources.total_count(),
            price_results=[{
                "channel": "이마트", "price_low": 29800, "price_high": 33000,
                "year_month": "2026-07", "source_urls": ["https://blog.naver.com/x/1"],
            }],
        )

    monkeypatch.setattr(main_module, "run_job", fake_run_job)

    client = TestClient(main_module.app)
    response = client.post("/jobs", json={"wine_name": "몬테스 알파", "brand": "몬테스"})
    job_id = response.json()["job_id"]

    body = client.get(f"/jobs/{job_id}").json()
    assert body["price_results"] == [{
        "channel": "이마트", "price_low": 29800, "price_high": 33000,
        "year_month": "2026-07", "source_urls": ["https://blog.naver.com/x/1"],
    }]
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd backend && .venv/bin/python3 -m pytest tests/test_main.py -v -k price_results`
Expected: FAIL — `KeyError: 'price_results'`

- [ ] **Step 3: 최소 구현 작성**

`backend/app/main.py`의 `_run_job_in_background` 안에 새 클로저 2개 추가
(기존 `fetch_web_items` 정의 다음, `run_job(...)` 호출 앞):

```python
            def fetch_blog_body(url: str):
                return collectors.fetch_blog_full_body(url, client)

            def fetch_wassap_body(source, url: str):
                return collectors.fetch_wassap_full_body(source.cafe_numeric_id, url, client, settings.naver_cookie)
```

`run_job(...)` 호출에 인자 3개 추가(기존 `fetch_international_items=fetch_international_items,` 다음, `deadline=` 앞):

```python
                fetch_international_items=fetch_international_items,
                fetch_blog_body=fetch_blog_body,
                fetch_wassap_body=fetch_wassap_body,
                insert_channel_price=_insert_channel_price,
                deadline=time.monotonic() + 60,
```

`_insert_article` 함수(약 81번째 줄) 바로 아래에 같은 패턴으로 추가:

```python
def _insert_channel_price(wine_query: str, channel: str, price_low: int, price_high: int,
                           year_month: str, source_type: str, source_url: str) -> int:
    return _with_connection(lambda conn: db.insert_channel_price(
        conn, wine_query, channel, price_low, price_high, year_month, source_type, source_url,
    ))
```

`get_job()` 함수의 반환 딕셔너리(약 205~234번째 줄)에 필드 추가:

```python
    return {
        "job_id": job.id,
        "status": job.status,
        "total": job.total,
        "done": job.done,
        "error": job.error,
        "results": [...],  # 기존 그대로
        "price_results": job.price_results,
        "failures": [...],  # 기존 그대로
    }
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd backend && .venv/bin/python3 -m pytest tests/test_main.py -v`
Expected: PASS 전체(기존 테스트 포함)

- [ ] **Step 5: 전체 백엔드 테스트 스위트 회귀 확인**

Run: `cd backend && .venv/bin/python3 -m pytest -v`
Expected: PASS 전체

- [ ] **Step 6: 커밋**

```bash
git add backend/app/main.py backend/tests/test_main.py
git commit -m "feat: /jobs 응답에 price_results 배선"
```

---

### Task 6: 프론트엔드 — "가격" 표 섹션 (뉴스·매거진과 블로그 사이)

**Files:**
- Modify: `js/app.js`

**Interfaces:**
- Consumes: `GET /jobs/{id}` 응답의 `price_results` 필드(Task 5) — 각 항목
  `{channel, price_low, price_high, year_month, source_urls}`

- [ ] **Step 1: `DISPLAY_GROUPS` 추가 + `initIncrementalResults` 분기**

`js/app.js`의 `RESULT_CATEGORY_META` 정의(32번째 줄) 바로 아래에 추가(기존
`RESULT_CATEGORY_META`는 그대로 둔다 — 진행률바/그룹핑 로직이 계속 이 5개 기준으로
동작해야 함):

```js
// 화면에 보여줄 순서 — RESULT_CATEGORY_META(5개, 진행률바 기준)와 별개로
// "가격"을 뉴스·매거진과 블로그 사이에 끼워 넣기 위한 전용 목록
const DISPLAY_GROUPS=[
  {key:'news', label:'뉴스·매거진', kind:'cards'},
  {key:'price', label:'가격', kind:'table'},
  {key:'blog', label:'네이버 블로그', kind:'cards'},
  {key:'youtube', label:'유튜브', kind:'cards'},
  {key:'wassap', label:'와쌉카페', kind:'cards'},
  {key:'international', label:'해외소스', kind:'cards'},
];
```

`initIncrementalResults()` 함수(348번째 줄 부근)를 교체:

```js
function initIncrementalResults(){
  renderedResultUrls=new Set();
  resultsGroupsEl.innerHTML='';
  DISPLAY_GROUPS.forEach(c=>{
    const groupEl=document.createElement('div');
    groupEl.className='result-group hidden';
    groupEl.dataset.category=c.key;
    const groupTitle=document.createElement('div');
    groupTitle.className='result-group-title';
    const countSpan=document.createElement('span');
    countSpan.className='result-group-count';
    countSpan.textContent='0';
    groupTitle.textContent=c.label+' ';
    groupTitle.appendChild(countSpan);
    groupEl.appendChild(groupTitle);

    if(c.kind==='table'){
      const table=document.createElement('table');
      table.className='ds-table';
      const thead=document.createElement('thead');
      thead.innerHTML='<tr><th>채널</th><th>가격</th><th>년월</th><th>출처</th></tr>';
      table.appendChild(thead);
      table.appendChild(document.createElement('tbody'));
      groupEl.appendChild(table);
    }else{
      const grid=document.createElement('div');
      grid.className='result-grid';
      groupEl.appendChild(grid);
    }
    resultsGroupsEl.appendChild(groupEl);
  });
}
```

- [ ] **Step 2: `renderPriceResults` 추가 + `pollJob`에서 호출**

`appendIncrementalResults` 함수(370번째 줄 부근) 바로 다음에 추가:

```js
function renderPriceResults(priceResults){
  const groupEl=resultsGroupsEl.querySelector('[data-category="price"]');
  const tbody=groupEl.querySelector('tbody');
  tbody.innerHTML='';
  if(!priceResults || !priceResults.length){
    groupEl.classList.add('hidden');
    return;
  }
  groupEl.classList.remove('hidden');
  priceResults.forEach(p=>{
    const tr=document.createElement('tr');

    const tdChannel=document.createElement('td');
    tdChannel.textContent=p.channel;

    const tdPrice=document.createElement('td');
    tdPrice.textContent = p.price_low===p.price_high
      ? `${p.price_low.toLocaleString()}원`
      : `${p.price_low.toLocaleString()}원 ~ ${p.price_high.toLocaleString()}원`;

    const tdMonth=document.createElement('td');
    tdMonth.textContent=p.year_month;

    const tdSource=document.createElement('td');
    p.source_urls.forEach((u, i)=>{
      const a=document.createElement('a');
      a.href=u; a.target='_blank'; a.rel='noopener';
      a.textContent=`[출처${i+1}]`;
      tdSource.appendChild(a);
      if(i<p.source_urls.length-1) tdSource.appendChild(document.createTextNode(' '));
    });

    tr.appendChild(tdChannel); tr.appendChild(tdPrice); tr.appendChild(tdMonth); tr.appendChild(tdSource);
    tbody.appendChild(tr);
  });
  groupEl.querySelector('.result-group-count').textContent=priceResults.length;
}
```

`pollJob()` 함수(173번째 줄 부근) 안, `appendIncrementalResults(job.results, query);`
바로 다음 줄에 추가:

```js
    appendIncrementalResults(job.results, query);
    renderPriceResults(job.price_results||[]);
```

- [ ] **Step 3: 로컬에서 실제로 확인 (브라우저)**

Run: `cd backend && .venv/bin/python3 -m uvicorn app.main:app --reload --port 8000`
(별도 터미널) 루트에서 정적 서버: `python3 -m http.server 8080`

브라우저로 `http://localhost:8080`을 열고(API_BASE가 `http://localhost:8000`을
가리키는지 `js/app.js` 상단 확인 필요 — 다르면 이 스텝에서만 임시로 맞춰서 확인),
가격 언급이 있을 만한 흔한 와인명(예: "까스텔로 몬테스" 등 실제 취급 브랜드)으로
검색해서:
- "가격" 섹션이 뉴스·매거진과 블로그 사이에 뜨는지
- 채널·가격·년월·출처 컬럼이 표로 나오는지, 값 없는 채널은 행 자체가 없는지
- 가격 언급이 하나도 없으면 "가격" 섹션 자체가 안 보이는지(hidden)

Expected: 위 조건 전부 만족. 문제 있으면 코드 읽고 고친 뒤 다시 확인.

- [ ] **Step 4: 커밋**

```bash
git add js/app.js
git commit -m "feat: 검색 결과 화면에 채널별 가격 표 섹션 추가"
```

---

## 완료 기준

- `cd backend && .venv/bin/python3 -m pytest -v` 전체 통과(기존 테스트 포함 회귀 없음)
- 실제 DB에 `wine_channel_prices` 테이블 생성되고 INSERT/SELECT 확인됨(Task 2)
- 실제 블로그/와쌉 게시글 본문을 실제로 가져와 텍스트가 나옴(Task 3)
- 브라우저로 실제 검색해서 "가격" 섹션이 뉴스·매거진과 블로그 사이에 표로
  나오는 것 확인(Task 6)
