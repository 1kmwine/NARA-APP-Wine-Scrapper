# 이미지 속 가격 추출 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 본문 텍스트에서 가격을 못 찾은 블로그·와쌉 글에 한해, 첨부 이미지(결제화면 캡처 등)에서 최종 결제금액을 읽어 기존 채널별 가격 저장 흐름에 합류시킨다 (`docs/superpowers/specs/2026-09-03-image-price-extraction-design.md`).

**Architecture:** `collectors.py`가 본문 HTML에서 `<img>` URL을 같이 뽑아 `FetchedBody(text, image_urls)`로 돌려준다. `jobs.py`의 `_collect_prices`가 텍스트 추출 0건일 때만 이미지 경로를 타고, 주입된 `extract_image_price` 콜러블이 이미지를 내려받아 추출기(Gemini Vision 또는 Tesseract OCR)로 최종 결제금액을 읽는다. 채널은 이미지가 아니라 글 제목/본문에서 기존 `CHANNEL_ALIASES`로 확정하며, 채널이 하나로 확정되지 않으면 저장하지 않는다. 어느 추출기를 쓸지는 벤치마크 스크립트의 실측 결과로 정하고, 그 전까지 기본값은 `off`다.

**Tech Stack:** Python 3.11, FastAPI, httpx(REST로 Gemini 호출 — 이 레포는 `google-genai` SDK를 안 쓴다), pytesseract + Pillow(OCR 후보), pytest.

## Global Constraints

- 테스트 실행은 항상 `cd backend && source .venv/bin/activate && pytest -v` (README 기준).
- Gemini 호출은 기존 `briefing_summary.call_gemini()` 패턴을 그대로 따른다 — httpx REST,
  모델 `gemini-flash-latest`(무료 티어는 버전 고정 모델이 quota=0), `responseMimeType=application/json`.
- `GEMINI_API_KEY`는 `Settings`에 넣지 않는다 — 기존 `main.py`처럼 `os.environ.get`으로
  직접 읽는다(키 없는 배포에서도 `get_settings()`가 죽지 않아야 함).
- 기존 가격 추출의 "지어내지 않음" 원칙 유지 — 애매하면 저장하지 않는다.
- 실제 비밀번호/키/쿠키는 트래킹되는 파일에 절대 쓰지 않는다.

---

## File Structure

```
backend/app/
  collectors.py          # 수정: extract_image_urls(), FetchedBody, 두 fetcher 반환 타입
  price_extraction.py    # 수정: resolve_single_channel() 추가
  price_image_gemini.py  # 신규: Gemini Vision 추출기
  price_image_ocr.py     # 신규: Tesseract OCR 추출기
  image_price.py         # 신규: 이미지 다운로드 + 추출기 선택 + 오케스트레이션
  jobs.py                # 수정: _collect_prices가 이미지 경로 타도록
  main.py                # 수정: extract_image_price 콜러블 배선
backend/tests/
  test_collectors.py       # 수정: 기존 fetcher 테스트 2건 (str → FetchedBody)
  test_price_extraction.py # 수정: resolve_single_channel 테스트 추가
  test_price_image_gemini.py  # 신규
  test_price_image_ocr.py     # 신규
  test_image_price.py         # 신규
  test_jobs.py             # 수정: 이미지 폴백 경로 테스트 추가
js/app.js                # 수정: priced_from_image 상태 라벨
scripts/bench_image_price.py  # 신규: 두 추출기 실측 비교
```

## Scope Check

단일 기능(이미지 가격 추출) — 분해 불필요.

---

### Task 1: 본문 HTML에서 이미지 URL 뽑기

**Files:**
- Modify: `backend/app/collectors.py`
- Test: `backend/tests/test_collectors.py`

**Interfaces:**
- Produces: `extract_image_urls(html_str: str, limit: int = 5) -> list[str]`

- [ ] **Step 1: 실패하는 테스트 작성** — `backend/tests/test_collectors.py` 맨 아래에 추가

```python
from app.collectors import extract_image_urls


def test_extract_image_urls_keeps_body_photos_in_order():
    html = (
        '<p>사진</p>'
        '<img src="https://mblogthumb-phinf.pstatic.net/a.jpg">'
        '<img src="https://mblogthumb-phinf.pstatic.net/b.jpg">'
    )
    assert extract_image_urls(html) == [
        "https://mblogthumb-phinf.pstatic.net/a.jpg",
        "https://mblogthumb-phinf.pstatic.net/b.jpg",
    ]


def test_extract_image_urls_drops_profile_and_link_thumbnails():
    # 2026-09-03 실측: 블로그 글 1건의 <img> 11개 중 작성자 프로필(blogpfthumb),
    # 외부 링크 카드 썸네일(dthumb)이 섞여 있다 — 본문 사진이 아니라 제외한다.
    html = (
        '<img src="https://blogpfthumb-phinf.pstatic.net/profile.jpg">'
        '<img src="https://dthumb-phinf.pstatic.net/?src=external">'
        '<img src="https://ssl.pstatic.net/static/icon.png">'
        '<img src="https://mblogthumb-phinf.pstatic.net/real.jpg">'
    )
    assert extract_image_urls(html) == ["https://mblogthumb-phinf.pstatic.net/real.jpg"]


def test_extract_image_urls_drops_gif_emoticons():
    html = '<img src="https://cafeptthumb-phinf.pstatic.net/sticker.gif"><img src="https://cafeptthumb-phinf.pstatic.net/pay.png">'
    assert extract_image_urls(html) == ["https://cafeptthumb-phinf.pstatic.net/pay.png"]


def test_extract_image_urls_applies_limit():
    html = "".join(f'<img src="https://mblogthumb-phinf.pstatic.net/{i}.jpg">' for i in range(10))
    assert len(extract_image_urls(html, limit=3)) == 3


def test_extract_image_urls_unescapes_html_entities():
    # Smart Editor 콘텐츠는 &amp; 같은 엔티티가 그대로 들어있다 — 그대로 두면
    # 다운로드 URL이 깨진다.
    html = '<img src="https://mblogthumb-phinf.pstatic.net/a.jpg?type=w800&amp;quality=90">'
    assert extract_image_urls(html) == ["https://mblogthumb-phinf.pstatic.net/a.jpg?type=w800&quality=90"]
```

- [ ] **Step 2: 실패 확인**

Run: `cd backend && source .venv/bin/activate && pytest tests/test_collectors.py -k extract_image_urls -v`
Expected: FAIL (`ImportError: cannot import name 'extract_image_urls'`)

- [ ] **Step 3: 구현** — `backend/app/collectors.py`의 `_html_to_lines()` 정의 바로 위(현재 762행 근처)에 추가

```python
_IMG_SRC_RE = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE)
# 본문 사진이 아닌 것들 — 작성자 프로필(blogpfthumb), 외부 링크 카드 썸네일(dthumb),
# 정적 아이콘, 애니메이션 스티커(.gif). 2026-09-03 실측 기준.
_NON_CONTENT_IMG_RE = re.compile(
    r'blogpfthumb-phinf|dthumb-phinf|ssl\.pstatic\.net/static|\.gif(?:\?|$)',
    re.IGNORECASE,
)


def extract_image_urls(html_str: str, limit: int = 5) -> list[str]:
    """본문 HTML에서 사진 URL을 순서대로 뽑는다. _html_to_lines()는 태그를 벗기면서
    <img>까지 버리므로, 이미지 가격 추출용으로 벗기기 전에 따로 뽑아둔다.

    limit을 두는 이유: 사진 30장짜리 후기 글이 흔한데, 이미지 1장당 추출기 호출이
    한 번씩 붙으므로 호출 수·소요 시간 상한을 보장해야 한다."""
    urls: list[str] = []
    for match in _IMG_SRC_RE.finditer(html_str):
        url = html_module.unescape(match.group(1)).strip()
        if not url or _NON_CONTENT_IMG_RE.search(url):
            continue
        urls.append(url)
        if len(urls) >= limit:
            break
    return urls
```

- [ ] **Step 4: 통과 확인**

Run: `cd backend && source .venv/bin/activate && pytest tests/test_collectors.py -k extract_image_urls -v`
Expected: PASS (5 passed)

- [ ] **Step 5: 커밋**

```bash
git add backend/app/collectors.py backend/tests/test_collectors.py
git commit -m "feat: 본문 HTML에서 이미지 URL 추출 (프로필/링크썸네일 제외)"
```

---

### Task 2: 본문 fetcher가 이미지 URL도 함께 반환

**Files:**
- Modify: `backend/app/collectors.py`
- Test: `backend/tests/test_collectors.py`

**Interfaces:**
- Consumes: `extract_image_urls` (Task 1)
- Produces: `FetchedBody(NamedTuple)` with fields `text: str`, `image_urls: list[str]`;
  `fetch_blog_full_body(...) -> FetchedBody | None`, `fetch_wassap_full_body(...) -> FetchedBody | None`

- [ ] **Step 1: 실패하는 테스트 작성** — `backend/tests/test_collectors.py`의 기존 두 테스트를 아래로 **교체**하고, 신규 2건을 추가

교체 대상 1: `test_fetch_blog_full_body_uses_mobile_url_and_strips_tags`

```python
def test_fetch_blog_full_body_uses_mobile_url_and_strips_tags():
    client = FakeMobileBlogClient({
        "naracellar/224352889386": "<p>이마트 7월 29,800원~33,000원 정도</p><br><p>완전 혜자</p>",
    })

    body = fetch_blog_full_body("https://blog.naver.com/naracellar/224352889386", client)

    assert body.text == "이마트 7월 29,800원~33,000원 정도\n완전 혜자"
    assert body.image_urls == []
```

교체 대상 2: `test_fetch_wassap_full_body_calls_article_detail_endpoint`

```python
def test_fetch_wassap_full_body_calls_article_detail_endpoint():
    client = FakeArticleDetailClient(ARTICLE_DETAIL_PAYLOAD)

    body = fetch_wassap_full_body("20564405", "https://cafe.naver.com/winerack24/369628", client, naver_cookie="fake-cookie")

    assert body.text == "CU 21,000원에 픽업했어요"
    assert body.image_urls == []
    assert client.last_call["headers"]["Cookie"] == "fake-cookie"
```

신규 2건 (파일 맨 아래에 추가):

```python
def test_fetch_blog_full_body_collects_image_urls():
    client = FakeMobileBlogClient({
        "naracellar/1": '<p>본문</p><img src="https://mblogthumb-phinf.pstatic.net/pay.jpg">',
    })

    body = fetch_blog_full_body("https://blog.naver.com/naracellar/1", client)

    assert body.text == "본문"
    assert body.image_urls == ["https://mblogthumb-phinf.pstatic.net/pay.jpg"]


def test_fetch_wassap_full_body_collects_image_urls():
    payload = {"result": {"article": {
        "contentHtml": '<p>문의</p><img src="https://cafeptthumb-phinf.pstatic.net/pay.png">',
    }}}
    client = FakeArticleDetailClient(payload)

    body = fetch_wassap_full_body("20564405", "https://cafe.naver.com/winerack24/369628", client, naver_cookie="x")

    assert body.text == "문의"
    assert body.image_urls == ["https://cafeptthumb-phinf.pstatic.net/pay.png"]
```

- [ ] **Step 2: 실패 확인**

Run: `cd backend && source .venv/bin/activate && pytest tests/test_collectors.py -k full_body -v`
Expected: FAIL (`AttributeError: 'str' object has no attribute 'text'`)

- [ ] **Step 3: 구현** — `backend/app/collectors.py`

`extract_image_urls` 정의 아래에 타입 추가:

```python
class FetchedBody(NamedTuple):
    """본문 텍스트와 그 글에 붙은 사진 URL을 같이 나른다 — 이미지 가격 추출이
    본문을 다시 내려받지 않아도 되게(한 번 받은 HTML에서 둘 다 뽑는다)."""
    text: str
    image_urls: list[str]
```

파일 상단 import에 `NamedTuple` 추가:

```python
from typing import NamedTuple
```

`fetch_blog_full_body()`의 `return` 부분을 교체:

```python
    try:
        response = client.get(f"https://m.blog.naver.com/{blog_id}/{log_no}", timeout=10.0)
        response.raise_for_status()
        return FetchedBody(text=_html_to_lines(response.text), image_urls=extract_image_urls(response.text))
    except Exception:  # noqa: BLE001 — 이 게시글만 스킵, 전체 검색은 계속
        return None
```

`fetch_wassap_full_body()`의 `return` 부분을 교체:

```python
        response.raise_for_status()
        content_html = response.json().get("result", {}).get("article", {}).get("contentHtml") or ""
        text = _html_to_lines(content_html)
        if not text:
            return None
        return FetchedBody(text=text, image_urls=extract_image_urls(content_html))
```

- [ ] **Step 4: 통과 확인**

Run: `cd backend && source .venv/bin/activate && pytest tests/test_collectors.py -v`
Expected: PASS (기존 테스트 포함 전부)

- [ ] **Step 5: 커밋**

```bash
git add backend/app/collectors.py backend/tests/test_collectors.py
git commit -m "feat: 본문 fetcher가 이미지 URL도 함께 반환 (FetchedBody)"
```

---

### Task 3: 와쌉 이미지 실측 확인 (수동)

**Files:** 없음 (확인만 — 결과에 따라 Task 7의 쿠키 처리 여부가 갈린다)

스펙에 남겨둔 미확인 항목: 와쌉 게시글 API의 `contentHtml`에 실제로 `<img>`가 들어있는지,
그 이미지 CDN이 쿠키 없이 받아지는지. 블로그는 2026-09-03 확인 완료
(`mblogthumb-phinf.pstatic.net`, 인증 불필요).

- [ ] **Step 1: 실제 글 하나로 contentHtml 확인**

```bash
cd /Users/jaeyungsong/Projects/NARA-APP-Wine-Scrapper
set -a && source backend/.env && set +a
source backend/.venv/bin/activate
python3 -c "
import httpx, os, re
h = {'Cookie': os.environ['NAVER_COOKIE'], 'Referer': 'https://cafe.naver.com/winerack24/367941',
     'Origin': 'https://cafe.naver.com', 'Accept': 'application/json, text/plain, */*',
     'User-Agent': 'Mozilla/5.0', 'X-Cafe-Product': 'pc', 'X-Cafe-Version': '1.0', 'X-Cafe-Phase': 'real'}
r = httpx.get('https://article.cafe.naver.com/gw/v4/cafes/20564405/articles/367941',
              params={'query':'','fromPopular':'true','useCafeId':'true','requestFrom':'A'},
              headers=h, timeout=15)
html = r.json().get('result',{}).get('article',{}).get('contentHtml','')
imgs = re.findall(r'<img[^>]+src=[\"\\']([^\"\\']+)', html)
print('status', r.status_code, 'html len', len(html), 'img count', len(imgs))
for u in imgs[:5]: print(' -', u[:120])
"
```

기대: `img count`가 1 이상, `cafeptthumb-phinf.pstatic.net` 계열 URL.
(글 `367941`은 스펙의 근거가 된 GS25 결제화면 글이다.)

- [ ] **Step 2: 이미지가 쿠키 없이 받아지는지 확인**

```bash
python3 -c "
import httpx
url = '<Step 1에서 출력된 첫 이미지 URL>'
r = httpx.get(url, timeout=15, headers={'User-Agent':'Mozilla/5.0'})
print('status', r.status_code, 'type', r.headers.get('content-type'), 'bytes', len(r.content))
"
```

기대: 200 + `image/*` + 0보다 큰 바이트 수.

- [ ] **Step 3: 결과 기록**

- `img count`가 0이면 → 와쌉은 이미지 경로를 못 탄다. 이 사실을 스펙 문서
  "범위 밖"에 한 줄 덧붙이고, 이후 태스크는 블로그만 대상으로 진행한다.
- Step 2가 403/401이면 → Task 7의 `download_image()`에 `Referer` + `NAVER_COOKIE`
  헤더를 붙여야 한다(Task 7 Step 3의 주석 참고).
- 둘 다 정상이면 → 추가 작업 없이 다음 태스크로.

커밋할 코드 변경은 없다. 스펙 문서를 고친 경우에만 커밋한다:

```bash
git add docs/superpowers/specs/2026-09-03-image-price-extraction-design.md
git commit -m "docs: 와쌉 이미지 실측 결과 반영"
```

---

### Task 4: 글 텍스트에서 채널 하나 확정

**Files:**
- Modify: `backend/app/price_extraction.py`
- Test: `backend/tests/test_price_extraction.py`

**Interfaces:**
- Produces: `resolve_single_channel(text: str) -> str | None`

- [ ] **Step 1: 실패하는 테스트 작성** — `backend/tests/test_price_extraction.py` 맨 아래에 추가

```python
from app.price_extraction import resolve_single_channel


def test_resolve_single_channel_returns_the_only_channel():
    assert resolve_single_channel("GS25 오늘의 와인 - 베터하프 문의") == "GS25"


def test_resolve_single_channel_returns_none_when_no_channel():
    assert resolve_single_channel("베터하프 마셔봤어요 맛있네요") is None


def test_resolve_single_channel_returns_none_when_ambiguous():
    # 채널이 둘 이상이면 이미지 속 가격이 어느 채널 것인지 확정할 수 없다 —
    # 지어내지 않고 버린다.
    assert resolve_single_channel("이마트랑 GS25 둘 다 가봤는데") is None


def test_resolve_single_channel_does_not_double_count_emart24():
    # "이마트24"는 "이마트" 패턴에 negative lookahead가 걸려 있어 한 채널로만 잡힌다.
    assert resolve_single_channel("이마트24에서 봤어요") == "이마트24"
```

- [ ] **Step 2: 실패 확인**

Run: `cd backend && source .venv/bin/activate && pytest tests/test_price_extraction.py -k resolve_single_channel -v`
Expected: FAIL (`ImportError: cannot import name 'resolve_single_channel'`)

- [ ] **Step 3: 구현** — `backend/app/price_extraction.py`의 `extract_channel_prices()` 정의 위에 추가

```python
def resolve_single_channel(text: str) -> str | None:
    """글 전체 텍스트에서 채널을 하나로 확정한다. 이미지에서 읽은 가격은 채널
    정보가 없으므로(결제화면에 채널명이 안 찍히는 경우가 많다) 글 텍스트에서
    채널을 정해야 한다.

    채널이 0개거나 2개 이상이면 None — 어느 채널 가격인지 확정할 수 없으면
    저장하지 않는다(기존 '지어내지 않음' 원칙)."""
    found = [channel for channel, pattern in _CHANNEL_PATTERNS.items() if pattern.search(text)]
    return found[0] if len(found) == 1 else None
```

- [ ] **Step 4: 통과 확인**

Run: `cd backend && source .venv/bin/activate && pytest tests/test_price_extraction.py -v`
Expected: PASS (기존 테스트 포함 전부)

- [ ] **Step 5: 커밋**

```bash
git add backend/app/price_extraction.py backend/tests/test_price_extraction.py
git commit -m "feat: 글 텍스트에서 채널 단일 확정 (resolve_single_channel)"
```

---

### Task 5: Gemini Vision 추출기

**Files:**
- Create: `backend/app/price_image_gemini.py`
- Test: `backend/tests/test_price_image_gemini.py`

**Interfaces:**
- Produces: `PROMPT`, `extract_final_price(image_bytes: bytes, mime_type: str, api_key: str, client=None, model: str = "gemini-flash-latest") -> int | None`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# backend/tests/test_price_image_gemini.py
import json

from app.price_image_gemini import extract_final_price


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def _gemini_payload(obj: dict) -> dict:
    return {"candidates": [{"content": {"parts": [{"text": json.dumps(obj)}]}}]}


class FakeClient:
    def __init__(self, response):
        self._response = response
        self.last_call = None

    def post(self, url, *, params=None, json=None, timeout=None):
        self.last_call = {"url": url, "params": params, "json": json}
        return self._response


def test_extract_final_price_reads_final_payment_amount():
    client = FakeClient(FakeResponse(_gemini_payload({"final_price": 15920, "label": "최종 결제 금액"})))

    assert extract_final_price(b"img", "image/png", api_key="k", client=client) == 15920


def test_extract_final_price_sends_image_inline_with_json_mime():
    client = FakeClient(FakeResponse(_gemini_payload({"final_price": 15920, "label": "결제 금액"})))

    extract_final_price(b"img-bytes", "image/jpeg", api_key="k", client=client)

    parts = client.last_call["json"]["contents"][0]["parts"]
    assert parts[1]["inlineData"]["mimeType"] == "image/jpeg"
    assert parts[1]["inlineData"]["data"]  # base64 인코딩된 값이 실려야 한다
    assert client.last_call["json"]["generationConfig"]["responseMimeType"] == "application/json"
    assert client.last_call["params"] == {"key": "k"}


def test_extract_final_price_returns_none_when_model_finds_no_price():
    client = FakeClient(FakeResponse(_gemini_payload({"final_price": None, "label": None})))

    assert extract_final_price(b"img", "image/png", api_key="k", client=client) is None


def test_extract_final_price_returns_none_on_http_error():
    # 무료 티어에서 429/503이 드물지 않다 — 이 이미지만 스킵하고 검색은 계속돼야 하므로
    # 예외를 밖으로 던지지 않는다.
    client = FakeClient(FakeResponse({}, status_code=503))

    assert extract_final_price(b"img", "image/png", api_key="k", client=client) is None


def test_extract_final_price_returns_none_on_malformed_response():
    client = FakeClient(FakeResponse({"candidates": []}))

    assert extract_final_price(b"img", "image/png", api_key="k", client=client) is None


def test_extract_final_price_returns_none_on_non_integer_value():
    client = FakeClient(FakeResponse(_gemini_payload({"final_price": "열다섯", "label": "?"})))

    assert extract_final_price(b"img", "image/png", api_key="k", client=client) is None
```

- [ ] **Step 2: 실패 확인**

Run: `cd backend && source .venv/bin/activate && pytest tests/test_price_image_gemini.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'app.price_image_gemini'`)

- [ ] **Step 3: 구현**

```python
# backend/app/price_image_gemini.py
from __future__ import annotations
import base64
import json
import logging

import httpx

logger = logging.getLogger(__name__)

PROMPT = (
    "이 이미지는 와인 구매/결제 화면 캡처거나 행사 가격 안내다. "
    "소비자가 실제로 지불한 최종 결제금액(원)을 숫자 하나로만 읽어라.\n"
    "- '최종 결제 금액', '결제 금액', '총 결제금액' 같은 라벨이 있으면 그 값을 쓴다.\n"
    "- 정가/총 상품금액과 할인 후 결제금액이 같이 있으면 할인 후 결제금액을 쓴다.\n"
    "- 가격이 안 보이거나 확신이 없으면 지어내지 말고 null로 답한다.\n"
    '반드시 이 JSON 형식으로만 답하라: {"final_price": 15920, "label": "최종 결제 금액"} '
    '또는 {"final_price": null, "label": null}'
)


def extract_final_price(
    image_bytes: bytes,
    mime_type: str,
    api_key: str,
    client=None,
    model: str = "gemini-flash-latest",
) -> int | None:
    """이미지에서 최종 결제금액을 읽는다. 못 읽으면 None.

    호출 실패(429/503/타임아웃)나 응답 파싱 실패는 예외를 던지지 않고 None —
    이 이미지 하나만 스킵하고 검색 전체는 계속돼야 한다.

    model 기본값이 -latest 별칭인 이유는 briefing_summary.call_gemini와 같다:
    이 API 키의 무료 티어는 버전 고정 모델이 quota=0이다."""
    http = client or httpx
    try:
        response = http.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            params={"key": api_key},
            json={
                "contents": [{"parts": [
                    {"text": PROMPT},
                    {"inlineData": {"mimeType": mime_type, "data": base64.b64encode(image_bytes).decode()}},
                ]}],
                "generationConfig": {"responseMimeType": "application/json", "temperature": 0.0},
            },
            timeout=30.0,
        )
        response.raise_for_status()
        text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
        value = json.loads(text).get("final_price")
    except Exception:  # noqa: BLE001 — 이 이미지만 스킵
        logger.exception("Gemini 이미지 가격 추출 실패")
        return None
    return value if isinstance(value, int) else None
```

- [ ] **Step 4: 통과 확인**

Run: `cd backend && source .venv/bin/activate && pytest tests/test_price_image_gemini.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: 커밋**

```bash
git add backend/app/price_image_gemini.py backend/tests/test_price_image_gemini.py
git commit -m "feat: Gemini Vision 이미지 가격 추출기"
```

---

### Task 6: Tesseract OCR 추출기

**Files:**
- Create: `backend/app/price_image_ocr.py`
- Modify: `backend/requirements.txt`
- Test: `backend/tests/test_price_image_ocr.py`

**Interfaces:**
- Produces: `extract_final_price(image_bytes: bytes, mime_type: str) -> int | None`,
  `parse_price_from_ocr_text(text: str) -> int | None`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# backend/tests/test_price_image_ocr.py
from app.price_image_ocr import parse_price_from_ocr_text


def test_parses_price_on_the_same_line_as_label():
    assert parse_price_from_ocr_text("최종 결제 금액 15,920원") == 15920


def test_parses_price_on_the_line_after_label():
    # 결제화면은 라벨과 금액이 좌우로 떨어져 있어 OCR에서 줄이 갈리는 경우가 많다.
    text = "최종 결제 금액\n15,920원\n포인트 적립 16P"
    assert parse_price_from_ocr_text(text) == 15920


def test_prefers_final_payment_over_total_product_amount():
    # 총 상품 금액(정가)과 최종 결제금액이 같이 찍힌 결제화면 — 결제금액을 쓴다.
    text = "총 상품 금액 19,900원\n할인금액 -3,980원\n최종 결제 금액 15,920원"
    assert parse_price_from_ocr_text(text) == 15920


def test_tolerates_ocr_separator_noise():
    # OCR이 쉼표를 마침표/공백으로 잘못 읽는 경우가 흔하다.
    assert parse_price_from_ocr_text("최종 결제 금액 15.920 원") == 15920
    assert parse_price_from_ocr_text("결제 금액 15 920원") == 15920


def test_returns_none_when_no_payment_label():
    # 라벨이 없으면 '가장 큰 숫자'식 추측을 하지 않는다 — 지어내지 않음.
    assert parse_price_from_ocr_text("와인 사진입니다 2026년 9월") is None


def test_returns_none_when_label_has_no_number_nearby():
    assert parse_price_from_ocr_text("최종 결제 금액\n확인 중") is None
```

- [ ] **Step 2: 실패 확인**

Run: `cd backend && source .venv/bin/activate && pytest tests/test_price_image_ocr.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'app.price_image_ocr'`)

- [ ] **Step 3: 구현**

```python
# backend/app/price_image_ocr.py
from __future__ import annotations
import io
import logging
import re

logger = logging.getLogger(__name__)

# "최종 결제 금액", "결제금액", "총 결제 금액" 등 — 결제화면에서 최종 지불액을 가리키는 라벨.
_LABEL_RE = re.compile(r'(최종\s*결제\s*금액|총\s*결제\s*금액|결제\s*금액|최종\s*결제|결제금액)')
# OCR은 천 단위 구분자를 쉼표/마침표/공백 아무거나로 뱉는다 — 셋 다 허용하고,
# 구분자를 지운 뒤 4~6자리(1,000~999,999원)만 가격으로 인정한다.
# price_extraction._PRICE_RE는 "29,800원" 형태를 정확히 요구해서 OCR 잡음에 약하다.
_OCR_PRICE_RE = re.compile(r'(\d{1,3}(?:[,.\s]\d{3})+|\d{4,6})\s*원')


def _first_price(line: str) -> int | None:
    match = _OCR_PRICE_RE.search(line)
    if not match:
        return None
    digits = re.sub(r'[,.\s]', '', match.group(1))
    if not 4 <= len(digits) <= 6:
        return None
    return int(digits)


def parse_price_from_ocr_text(text: str) -> int | None:
    """OCR 텍스트에서 최종 결제금액을 찾는다. 결제 라벨과 같은 줄, 없으면 바로
    다음 줄에서 찾는다. 라벨이 없으면 None — '가장 큰 숫자'식 추측은 하지 않는다."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for index, line in enumerate(lines):
        if not _LABEL_RE.search(line):
            continue
        value = _first_price(line)
        if value is not None:
            return value
        if index + 1 < len(lines):
            value = _first_price(lines[index + 1])
            if value is not None:
                return value
    return None


def extract_final_price(image_bytes: bytes, mime_type: str) -> int | None:
    """Tesseract로 이미지를 읽어 최종 결제금액을 뽑는다. 언어팩 미설치 등
    OCR 실패는 예외 대신 None — 이 이미지만 스킵하고 검색은 계속된다.

    서버에 apt 패키지 tesseract-ocr, tesseract-ocr-kor 설치가 필요하다."""
    try:
        import pytesseract
        from PIL import Image

        text = pytesseract.image_to_string(Image.open(io.BytesIO(image_bytes)), lang="kor+eng")
    except Exception:  # noqa: BLE001 — 이 이미지만 스킵
        logger.exception("OCR 이미지 가격 추출 실패")
        return None
    return parse_price_from_ocr_text(text)
```

- [ ] **Step 4: 의존성 추가** — `backend/requirements.txt` 맨 아래에 추가

```
pytesseract==0.3.13
pillow==11.0.0
```

```bash
cd backend && source .venv/bin/activate && pip install -r requirements.txt
```

- [ ] **Step 5: 통과 확인**

Run: `cd backend && source .venv/bin/activate && pytest tests/test_price_image_ocr.py -v`
Expected: PASS (6 passed)

- [ ] **Step 6: 커밋**

```bash
git add backend/app/price_image_ocr.py backend/tests/test_price_image_ocr.py backend/requirements.txt
git commit -m "feat: Tesseract OCR 이미지 가격 추출기"
```

---

### Task 7: 이미지 다운로드 + 추출기 선택 오케스트레이션

**Files:**
- Create: `backend/app/image_price.py`
- Test: `backend/tests/test_image_price.py`

**Interfaces:**
- Consumes: `price_image_gemini.extract_final_price` (Task 5), `price_image_ocr.extract_final_price` (Task 6)
- Produces: `download_image(url, client, cookie=None) -> tuple[bytes, str] | None`,
  `get_extractor(name: str, api_key: str | None) -> Callable[[bytes, str], int | None] | None`,
  `extract_price_from_images(image_urls, client, extractor, cookie=None) -> int | None`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# backend/tests/test_image_price.py
from app.image_price import download_image, extract_price_from_images, get_extractor


class FakeImageResponse:
    def __init__(self, content=b"bytes", content_type="image/png", status_code=200):
        self.content = content
        self.headers = {"content-type": content_type}
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeImageClient:
    def __init__(self, response_by_url):
        self._responses = response_by_url
        self.calls = []

    def get(self, url, *, headers=None, timeout=None):
        self.calls.append({"url": url, "headers": headers})
        response = self._responses.get(url)
        if response is None:
            raise RuntimeError("not found")
        return response


def test_download_image_returns_bytes_and_mime():
    client = FakeImageClient({"https://x/a.png": FakeImageResponse(b"png-bytes", "image/png")})

    assert download_image("https://x/a.png", client) == (b"png-bytes", "image/png")


def test_download_image_returns_none_on_failure():
    client = FakeImageClient({})

    assert download_image("https://x/missing.png", client) is None


def test_download_image_returns_none_for_non_image_content_type():
    # 로그인 리다이렉트로 HTML이 돌아오는 경우 — 추출기에 넘기면 안 된다.
    client = FakeImageClient({"https://x/a.png": FakeImageResponse(b"<html>", "text/html")})

    assert download_image("https://x/a.png", client) is None


def test_download_image_sends_cookie_when_given():
    client = FakeImageClient({"https://x/a.png": FakeImageResponse()})

    download_image("https://x/a.png", client, cookie="NID_AUT=z")

    assert client.calls[0]["headers"]["Cookie"] == "NID_AUT=z"


def test_extract_price_from_images_returns_first_success():
    client = FakeImageClient({
        "https://x/1.png": FakeImageResponse(b"one"),
        "https://x/2.png": FakeImageResponse(b"two"),
    })
    seen = []

    def extractor(image_bytes, mime_type):
        seen.append(image_bytes)
        return 15920 if image_bytes == b"two" else None

    result = extract_price_from_images(["https://x/1.png", "https://x/2.png"], client, extractor)

    assert result == 15920
    assert seen == [b"one", b"two"]


def test_extract_price_from_images_stops_after_first_hit():
    client = FakeImageClient({
        "https://x/1.png": FakeImageResponse(b"one"),
        "https://x/2.png": FakeImageResponse(b"two"),
    })
    seen = []

    def extractor(image_bytes, mime_type):
        seen.append(image_bytes)
        return 15920

    extract_price_from_images(["https://x/1.png", "https://x/2.png"], client, extractor)

    assert seen == [b"one"]  # 첫 성공에서 멈춘다 — 같은 값 중복 저장·불필요한 호출 방지


def test_extract_price_from_images_skips_failed_downloads():
    client = FakeImageClient({"https://x/2.png": FakeImageResponse(b"two")})

    result = extract_price_from_images(
        ["https://x/gone.png", "https://x/2.png"], client, lambda b, m: 15920)

    assert result == 15920


def test_extract_price_from_images_returns_none_when_nothing_found():
    client = FakeImageClient({"https://x/1.png": FakeImageResponse(b"one")})

    assert extract_price_from_images(["https://x/1.png"], client, lambda b, m: None) is None


def test_get_extractor_off_returns_none():
    assert get_extractor("off", api_key="k") is None


def test_get_extractor_gemini_requires_api_key():
    assert get_extractor("gemini", api_key=None) is None
    assert get_extractor("gemini", api_key="k") is not None


def test_get_extractor_ocr_does_not_need_api_key():
    assert get_extractor("ocr", api_key=None) is not None


def test_get_extractor_unknown_name_returns_none():
    assert get_extractor("magic", api_key="k") is None
```

- [ ] **Step 2: 실패 확인**

Run: `cd backend && source .venv/bin/activate && pytest tests/test_image_price.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'app.image_price'`)

- [ ] **Step 3: 구현**

```python
# backend/app/image_price.py
from __future__ import annotations
import logging
from typing import Callable, Optional

from . import price_image_gemini, price_image_ocr

logger = logging.getLogger(__name__)

Extractor = Callable[[bytes, str], Optional[int]]

# 5MB 넘는 이미지는 건너뛴다 — 결제화면 캡처는 수백 KB면 충분하고, 큰 원본
# 사진을 그대로 모델에 실으면 호출이 느려지고 무료 티어 한도를 빨리 태운다.
MAX_IMAGE_BYTES = 5 * 1024 * 1024


def download_image(url: str, client, cookie: str | None = None) -> tuple[bytes, str] | None:
    """이미지를 내려받아 (bytes, mime)을 돌려준다. 실패하거나 이미지가 아니면 None.

    Task 3에서 카페 CDN이 401/403을 내면 cookie를 넘겨 호출한다(네이버 로그인
    쿠키). 블로그 CDN(mblogthumb-phinf)은 쿠키 없이 받아진다 — 2026-09-03 확인."""
    headers = {"User-Agent": "Mozilla/5.0"}
    if cookie:
        headers["Cookie"] = cookie
    try:
        response = client.get(url, headers=headers, timeout=15.0)
        response.raise_for_status()
    except Exception:  # noqa: BLE001 — 이 이미지만 스킵
        logger.warning("이미지 다운로드 실패: %s", url)
        return None
    mime_type = (response.headers.get("content-type") or "").split(";")[0].strip()
    if not mime_type.startswith("image/"):
        return None
    if len(response.content) > MAX_IMAGE_BYTES:
        return None
    return response.content, mime_type


def get_extractor(name: str, api_key: str | None) -> Extractor | None:
    """환경변수 IMAGE_PRICE_EXTRACTOR 값으로 추출기를 고른다.

    기본값은 'off' — 벤치마크(scripts/bench_image_price.py)로 Gemini/OCR 중
    어느 쪽이 나은지 정하기 전까지는 이미지 경로를 켜지 않는다."""
    if name == "gemini":
        if not api_key:
            logger.warning("IMAGE_PRICE_EXTRACTOR=gemini인데 GEMINI_API_KEY가 없다 — 이미지 추출 비활성")
            return None
        return lambda image_bytes, mime_type: price_image_gemini.extract_final_price(
            image_bytes, mime_type, api_key=api_key)
    if name == "ocr":
        return price_image_ocr.extract_final_price
    return None


def extract_price_from_images(
    image_urls: list[str], client, extractor: Extractor, cookie: str | None = None,
) -> int | None:
    """이미지들을 순서대로 보다가 첫 성공 값에서 멈춘다. 결제화면이 여러 장인 글이
    흔한데 같은 값을 중복 저장할 이유가 없고, 호출도 아껴야 한다."""
    for url in image_urls:
        downloaded = download_image(url, client, cookie=cookie)
        if downloaded is None:
            continue
        image_bytes, mime_type = downloaded
        price = extractor(image_bytes, mime_type)
        if price is not None:
            return price
    return None
```

- [ ] **Step 4: 통과 확인**

Run: `cd backend && source .venv/bin/activate && pytest tests/test_image_price.py -v`
Expected: PASS (12 passed)

- [ ] **Step 5: 커밋**

```bash
git add backend/app/image_price.py backend/tests/test_image_price.py
git commit -m "feat: 이미지 다운로드 + 추출기 선택 오케스트레이션"
```

---

### Task 8: 가격 job에 이미지 폴백 연결

**Files:**
- Modify: `backend/app/jobs.py`
- Test: `backend/tests/test_jobs.py`

**Interfaces:**
- Consumes: `collectors.FetchedBody` (Task 2), `price_extraction.resolve_single_channel` (Task 4)
- Produces: `run_price_job(..., extract_image_price: Callable[[list[str]], int | None] | None = None)`;
  `_collect_prices`가 `priced_from_image` 상태를 반환할 수 있게 된다

- [ ] **Step 1: 실패하는 테스트 작성** — `backend/tests/test_jobs.py` 맨 아래에 추가

```python
from app.collectors import FetchedBody


def test_run_price_job_falls_back_to_image_when_text_has_no_price():
    # 스펙의 근거 사례: GS25 와쌉 글은 본문에 가격 텍스트가 없고 결제화면 캡처
    # 이미지에만 15,920원이 찍혀 있다.
    store = JobStore()
    job = store.create("베터하프", "", total=1)
    sources = _empty_sources()
    inserted = []

    run_price_job(job.id, store, sources, "베터하프", "", **_price_deps(
        fetch_blog_items=lambda query: [CollectedItem(
            title="GS25 오늘의 와인 - 베터하프 문의", excerpt="", thumbnail_url=None,
            external_url="https://blog.naver.com/x/1", published_date="2026-08-04",
            source_name="블로그: x",
        )],
        fetch_blog_body=lambda url: FetchedBody(
            text="베터하프 이거 문의드려요", image_urls=["https://img/pay.png"]),
        extract_image_price=lambda urls: 15920,
        insert_channel_price=lambda *a, **k: inserted.append(a) or 1,
    ))

    result = store.get(job.id)
    assert result.price_checked_items[0]["status"] == "priced_from_image"
    assert inserted[0] == ("베터하프", "GS25", 15920, 15920, "2026-08", "blog_img", "https://blog.naver.com/x/1")


def test_run_price_job_does_not_use_images_when_text_price_found():
    # 본문에서 가격을 찾았으면 이미지는 보지 않는다 — 호출 최소화.
    store = JobStore()
    job = store.create("몬테스", "", total=1)
    sources = _empty_sources()
    image_calls = []

    run_price_job(job.id, store, sources, "몬테스", "", **_price_deps(
        fetch_blog_items=lambda query: [CollectedItem(
            title="후기", excerpt="", thumbnail_url=None,
            external_url="https://blog.naver.com/x/2", published_date="2026-06-15",
            source_name="블로그: x",
        )],
        fetch_blog_body=lambda url: FetchedBody(
            text="몬테스 이마트 29,800원", image_urls=["https://img/a.png"]),
        extract_image_price=lambda urls: image_calls.append(urls) or 9999,
    ))

    assert image_calls == []
    assert store.get(job.id).price_checked_items[0]["status"] == "priced"


def test_run_price_job_skips_image_price_when_channel_ambiguous():
    # 이미지에서 가격을 읽어도 글에서 채널이 하나로 확정 안 되면 저장하지 않는다.
    store = JobStore()
    job = store.create("베터하프", "", total=1)
    sources = _empty_sources()
    inserted = []

    run_price_job(job.id, store, sources, "베터하프", "", **_price_deps(
        fetch_blog_items=lambda query: [CollectedItem(
            title="이마트랑 GS25 비교", excerpt="", thumbnail_url=None,
            external_url="https://blog.naver.com/x/3", published_date="2026-08-04",
            source_name="블로그: x",
        )],
        fetch_blog_body=lambda url: FetchedBody(text="베터하프 어디가 싼가요", image_urls=["https://img/a.png"]),
        extract_image_price=lambda urls: 15920,
        insert_channel_price=lambda *a, **k: inserted.append(a) or 1,
    ))

    assert inserted == []
    assert store.get(job.id).price_checked_items[0]["status"] == "no_price"


def test_run_price_job_accepts_plain_string_body():
    # 기존 호출부·테스트 호환 — 문자열 본문이면 이미지 없는 글로 본다.
    store = JobStore()
    job = store.create("몬테스", "", total=1)
    sources = _empty_sources()

    run_price_job(job.id, store, sources, "몬테스", "", **_price_deps(
        fetch_blog_items=lambda query: [CollectedItem(
            title="후기", excerpt="", thumbnail_url=None,
            external_url="https://blog.naver.com/x/4", published_date="2026-06-15",
            source_name="블로그: x",
        )],
        fetch_blog_body=lambda url: "몬테스 이마트 29,800원",
    ))

    assert store.get(job.id).price_checked_items[0]["status"] == "priced"
```

`_price_deps`에 새 의존성 기본값을 추가한다(같은 파일의 기존 헬퍼 수정):

```python
def _price_deps(**overrides):
    deps = dict(
        fetch_blog_items=lambda query: [],
        fetch_wassap_items=lambda source: [],
        fetch_blog_body=lambda url: None,
        fetch_wassap_body=lambda source, url: None,
        insert_channel_price=lambda *a, **k: 1,
        get_price_history=lambda query: [],
        extract_image_price=None,
    )
    deps.update(overrides)
    return deps
```

- [ ] **Step 2: 실패 확인**

Run: `cd backend && source .venv/bin/activate && pytest tests/test_jobs.py -k image -v`
Expected: FAIL (`TypeError: run_price_job() got an unexpected keyword argument 'extract_image_price'`)

- [ ] **Step 3: 구현** — `backend/app/jobs.py`

파일 상단 import에 추가:

```python
from .price_extraction import (
    extract_channel_prices, merge_channel_prices_by_month, resolve_single_channel,
)
```

(기존 import 줄이 `from .price_extraction import extract_channel_prices, merge_channel_prices_by_month`
형태라면 위처럼 `resolve_single_channel`만 덧붙인다.)

`run_price_job` 시그니처에 파라미터 추가 — `get_price_history` 다음, `deadline` 앞:

```python
    extract_image_price: Callable[[list[str]], Optional[int]] | None = None,
```

`_collect_prices`를 아래로 교체(기존 함수 전체를 대체):

```python
    def _normalize_body(body) -> tuple[str | None, list[str]]:
        """fetch_*_body는 FetchedBody를 돌려주지만, 문자열을 돌려주는 호출부도
        계속 지원한다(기존 테스트/호출 호환). 문자열이면 이미지 없는 글로 본다."""
        if body is None:
            return None, []
        if isinstance(body, str):
            return body, []
        return body.text, list(body.image_urls)

    def _collect_prices(body, published_date: str | None, source_type: str,
                        source_url: str, title: str = "") -> str:
        """가격을 추출·저장하고, 이 글을 어떻게 처리했는지 상태 문자열을 돌려준다.
        화면의 '검색한 글' 목록에 사유를 그대로 보여주기 위한 값 —
        'no_body'(본문 못 가져옴) | 'unrelated'(검색어가 글에 없음, 다른 제품)
        | 'priced'(본문 텍스트에서 가격 저장) | 'priced_from_image'(이미지에서
        가격 저장) | 'no_price'(관련 글이지만 가격 못 찾음)."""
        body_text, image_urls = _normalize_body(body)
        if not body_text:
            return "no_body"
        if not fuzzy_find(f"{title}\n{body_text}", query):
            return "unrelated"  # 검색어가 글 어디에도 없다 — 다른 제품 글
        fallback_ym = (published_date or "")[:7] or _today_year_month()
        try:
            prices = extract_channel_prices(body_text, fallback_ym, query=query)
        except Exception:  # noqa: BLE001 — 추출 자체가 깨져도 이 소스만 생략, 검색 전체는 계속
            logger.exception("가격 추출 실패: %s", source_url)
            return "no_price"
        for p in prices:
            try:
                insert_channel_price(
                    query, p["channel"], p["price_low"], p["price_high"], p["year_month"],
                    source_type, source_url,
                )
            except Exception:  # noqa: BLE001 — DB 저장 실패는 로그만, 나머지 값 처리는 계속
                logger.exception("가격 저장 실패: %s", source_url)
        if prices:
            return "priced"
        # 본문 텍스트에 가격이 없을 때만 이미지를 본다 — 호출 최소화 + 같은
        # (source_url, channel, year_month) 키에 텍스트/이미지 값이 겹치지 않게.
        if not (extract_image_price and image_urls):
            return "no_price"
        channel = resolve_single_channel(f"{title}\n{body_text}")
        if channel is None:
            return "no_price"  # 어느 채널 가격인지 확정 불가 — 지어내지 않는다
        try:
            image_price = extract_image_price(image_urls)
        except Exception:  # noqa: BLE001 — 이 글만 생략
            logger.exception("이미지 가격 추출 실패: %s", source_url)
            return "no_price"
        if image_price is None:
            return "no_price"
        try:
            insert_channel_price(
                query, channel, image_price, image_price, fallback_ym,
                f"{source_type}_img", source_url,
            )
        except Exception:  # noqa: BLE001
            logger.exception("이미지 가격 저장 실패: %s", source_url)
            return "no_price"
        return "priced_from_image"
```

`Callable`/`Optional`이 이미 import 돼 있는지 확인하고 없으면 상단에 추가:

```python
from typing import Callable, Optional
```

- [ ] **Step 4: 통과 확인**

Run: `cd backend && source .venv/bin/activate && pytest tests/test_jobs.py -v`
Expected: PASS (기존 가격 job 테스트 포함 전부)

- [ ] **Step 5: 커밋**

```bash
git add backend/app/jobs.py backend/tests/test_jobs.py
git commit -m "feat: 본문 가격 0건일 때 이미지에서 가격 추출 (priced_from_image)"
```

---

### Task 9: main.py 배선

**Files:**
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_main.py` (기존 테스트가 깨지지 않는지만 확인)

**Interfaces:**
- Consumes: `image_price.get_extractor`, `image_price.extract_price_from_images` (Task 7)

- [ ] **Step 1: 구현** — `backend/app/main.py`의 `_run_price_job_in_background()` 안,
`fetch_wassap_body` 정의 다음에 추가

```python
            extractor = image_price.get_extractor(
                os.environ.get("IMAGE_PRICE_EXTRACTOR", "off"),
                os.environ.get("GEMINI_API_KEY"),
            )

            def extract_image_price(image_urls: list[str]):
                return image_price.extract_price_from_images(
                    image_urls, client, extractor, cookie=settings.naver_cookie)
```

`run_price_job(...)` 호출 인자에 추가(`get_price_history` 다음 줄):

```python
                extract_image_price=extract_image_price if extractor else None,
```

파일 상단 import에 추가:

```python
from . import image_price
```

(`os`는 이미 import 돼 있다 — 428행에서 `os.environ.get("GEMINI_API_KEY")`를 쓴다.)

- [ ] **Step 2: 전체 테스트 통과 확인**

Run: `cd backend && source .venv/bin/activate && pytest -v`
Expected: PASS (전부)

- [ ] **Step 3: `.env.example`에 새 환경변수 문서화** — `backend/.env.example`이 있으면 추가,
없으면 이 단계는 건너뛴다

```
# 이미지 속 가격 추출기: off | gemini | ocr (기본 off — 벤치마크로 정하기 전까지 비활성)
IMAGE_PRICE_EXTRACTOR=off
```

- [ ] **Step 4: 커밋**

```bash
git add backend/app/main.py backend/.env.example
git commit -m "feat: 이미지 가격 추출기 배선 (IMAGE_PRICE_EXTRACTOR 환경변수)"
```

---

### Task 10: 프론트 상태 라벨

**Files:**
- Modify: `js/app.js`

- [ ] **Step 1: 구현** — `js/app.js`의 `PRICE_STATUS_LABEL`(551행 근처)에 한 줄 추가

```javascript
/* 백엔드 run_price_job의 _collect_prices 반환값과 1:1로 맞춰야 한다 */
const PRICE_STATUS_LABEL={
  priced:'가격 추출',
  priced_from_image:'가격 추출 (이미지)',
  no_price:'가격 언급 없음',
  unrelated:'제외 — 검색어 없는 글(다른 제품)',
  no_body:'본문 가져오기 실패',
};
```

같은 파일의 회색 처리 조건도 두 상태를 모두 정상으로 취급하도록 수정(571행 근처):

```javascript
    if(it.status!=='priced' && it.status!=='priced_from_image') tdRelated.style.color='var(--color-text-muted)';
```

- [ ] **Step 2: 확인**

```bash
node --check js/app.js
```

Expected: 출력 없음(문법 오류 없음)

- [ ] **Step 3: 커밋**

```bash
git add js/app.js
git commit -m "feat: 가격검색 목록에 '가격 추출 (이미지)' 상태 표시"
```

---

### Task 11: 벤치마크 스크립트

**Files:**
- Create: `scripts/bench_image_price.py`
- Modify: `.gitignore` (`data/bench_images/` 추가)

**Interfaces:**
- Consumes: `app.price_image_gemini`, `app.price_image_ocr`, `app.collectors.extract_image_urls`

- [ ] **Step 1: 구현**

```python
# scripts/bench_image_price.py
"""이미지 가격 추출기 실측 비교 — Gemini Vision vs Tesseract OCR.

사용법:
  1) 샘플 수집:  python scripts/bench_image_price.py collect "베터 하프" "몬테스 클래식"
  2) 정답 라벨:  data/bench_images/labels.json을 열어 이미지마다 최종 결제금액을 적는다
                 (가격이 없는 이미지는 null — 오탐 측정용)
  3) 비교 실행:  python scripts/bench_image_price.py compare

실행은 backend 가상환경에서: cd backend && source .venv/bin/activate && cd .. && python scripts/...
"""
from __future__ import annotations
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import httpx  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

from app import price_image_gemini, price_image_ocr  # noqa: E402
from app.collectors import extract_image_urls, fetch_blog_full_body  # noqa: E402
from app.naver_search import search_blog  # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent / "backend" / ".env")

BENCH_DIR = Path(__file__).resolve().parent.parent / "data" / "bench_images"
LABELS_PATH = BENCH_DIR / "labels.json"


def collect(queries: list[str], per_query: int = 5) -> None:
    """검색어별 블로그 글에서 이미지를 내려받아 벤치 세트를 만든다."""
    BENCH_DIR.mkdir(parents=True, exist_ok=True)
    labels = json.loads(LABELS_PATH.read_text(encoding="utf-8")) if LABELS_PATH.exists() else {}
    with httpx.Client(follow_redirects=True, timeout=15.0) as client:
        for query in queries:
            items = search_blog(f"{query} 가격", os.environ["NAVER_CLIENT_ID"],
                                os.environ["NAVER_CLIENT_SECRET"], client, display=per_query)
            for item in items:
                body = fetch_blog_full_body(item["link"], client)
                if body is None:
                    continue
                for url in body.image_urls:
                    name = f"{abs(hash(url))}.img"
                    path = BENCH_DIR / name
                    if path.exists():
                        continue
                    try:
                        response = client.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15.0)
                        response.raise_for_status()
                    except Exception:  # noqa: BLE001
                        continue
                    path.write_bytes(response.content)
                    labels.setdefault(name, {"url": url, "mime": response.headers.get("content-type", "image/jpeg"),
                                             "final_price": "TODO"})
    LABELS_PATH.write_text(json.dumps(labels, ensure_ascii=False, indent=2), encoding="utf-8")
    todo = sum(1 for v in labels.values() if v.get("final_price") == "TODO")
    print(f"수집 완료: 이미지 {len(labels)}장, 라벨 미기입 {todo}장 → {LABELS_PATH}")


def _score(name: str, extractor, labels: dict) -> dict:
    correct = false_positive = missed = failed = 0
    started = time.monotonic()
    for filename, meta in labels.items():
        expected = meta.get("final_price")
        if expected == "TODO":
            continue
        image_bytes = (BENCH_DIR / filename).read_bytes()
        try:
            got = extractor(image_bytes, meta.get("mime", "image/jpeg"))
        except Exception:  # noqa: BLE001
            failed += 1
            continue
        if expected is None:
            if got is None:
                correct += 1
            else:
                false_positive += 1
        elif got == expected:
            correct += 1
        elif got is None:
            missed += 1
        else:
            false_positive += 1
    labeled = sum(1 for v in labels.values() if v.get("final_price") != "TODO")
    elapsed = time.monotonic() - started
    return {
        "extractor": name, "labeled": labeled, "correct": correct,
        "false_positive": false_positive, "missed": missed, "failed": failed,
        "sec_per_image": round(elapsed / labeled, 2) if labeled else 0.0,
    }


def compare() -> None:
    labels = json.loads(LABELS_PATH.read_text(encoding="utf-8"))
    api_key = os.environ.get("GEMINI_API_KEY")
    rows = []
    if api_key:
        rows.append(_score(
            "gemini",
            lambda b, m: price_image_gemini.extract_final_price(b, m, api_key=api_key),
            labels,
        ))
    else:
        print("GEMINI_API_KEY 없음 — gemini 추출기는 건너뜀")
    rows.append(_score("ocr", price_image_ocr.extract_final_price, labels))

    header = f"{'추출기':<8}{'라벨수':>7}{'정답':>6}{'오탐':>6}{'미검출':>7}{'실패':>6}{'초/장':>8}"
    print(header)
    print("-" * len(header))
    for row in rows:
        print(f"{row['extractor']:<8}{row['labeled']:>7}{row['correct']:>6}"
              f"{row['false_positive']:>6}{row['missed']:>7}{row['failed']:>6}{row['sec_per_image']:>8}")


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "collect":
        collect(sys.argv[2:] or ["베터 하프"])
    elif len(sys.argv) >= 2 and sys.argv[1] == "compare":
        compare()
    else:
        print(__doc__)
```

- [ ] **Step 2: `.gitignore`에 벤치 이미지 제외 추가**

```
data/bench_images/
```

(라벨 파일 `labels.json`도 이미지와 같은 디렉토리라 함께 제외된다 — 이미지 없이는
의미가 없는 파일이고, 벤치는 재수집으로 언제든 다시 만든다.)

- [ ] **Step 3: 스크립트가 문법적으로 실행 가능한지 확인**

```bash
cd backend && source .venv/bin/activate && cd .. && python scripts/bench_image_price.py
```

Expected: 사용법(docstring)이 출력된다.

- [ ] **Step 4: 커밋**

```bash
git add scripts/bench_image_price.py .gitignore
git commit -m "feat: 이미지 가격 추출기 벤치마크 스크립트"
```

---

### Task 12: 벤치마크 실행 및 추출기 채택

**Files:**
- Modify: `docs/superpowers/specs/2026-09-03-image-price-extraction-design.md` (채택 결과 절 추가)
- Modify: `backend/.env` (로컬), 서버 `.env` (배포 시)

- [ ] **Step 1: OCR 시스템 패키지 설치 (로컬)**

```bash
brew install tesseract tesseract-lang
tesseract --list-langs | grep kor
```

Expected: `kor`이 목록에 있다. (없으면 OCR 쪽 점수는 전부 `실패`로 나온다.)

- [ ] **Step 2: 샘플 수집**

```bash
cd backend && source .venv/bin/activate && cd ..
python scripts/bench_image_price.py collect "베터 하프" "몬테스 클래식" "1865 셀렉티드"
```

Expected: `수집 완료: 이미지 N장, 라벨 미기입 N장`

- [ ] **Step 3: 정답 라벨 기입**

`data/bench_images/labels.json`의 각 항목에서 `"final_price": "TODO"`를 실제 값으로 바꾼다.
이미지를 직접 눈으로 보고(Read 도구로 이미지 파일을 열어 확인) 최종 결제금액을 적는다.
가격이 없는 이미지(와인 사진, 풍경 등)는 `null`로 둔다 — 오탐률 측정에 쓰인다.

최소 20장 이상 라벨링한다(그중 가격 있는 이미지가 5장 이상이어야 정답률이 의미 있다).

- [ ] **Step 4: 비교 실행**

```bash
python scripts/bench_image_price.py compare
```

Expected: 두 행(gemini/ocr)이 있는 표. 429/503이 잦으면 `실패` 열이 커진다 — 그 자체가
"무료 티어 rate limit" 판단 근거다.

- [ ] **Step 5: 채택 결정 및 스펙 문서에 기록**

`docs/superpowers/specs/2026-09-03-image-price-extraction-design.md` 맨 아래에 추가:

```markdown
## 채택 결과 (YYYY-MM-DD)

| 추출기 | 라벨수 | 정답 | 오탐 | 미검출 | 실패 | 초/장 |
|---|---|---|---|---|---|---|
| gemini | ... | ... | ... | ... | ... | ... |
| ocr | ... | ... | ... | ... | ... | ... |

채택: `<gemini | ocr>` — <한두 문장 근거. 오탐이 0이 아닌 쪽은 없는 가격을
저장하게 되므로 정답률이 조금 낮더라도 오탐 0인 쪽을 우선한다.>
```

- [ ] **Step 6: 채택된 추출기를 기본값으로 설정**

로컬 `backend/.env`에 추가(채택 결과에 맞춰 값 지정):

```
IMAGE_PRICE_EXTRACTOR=<gemini 또는 ocr>
```

- [ ] **Step 7: 실제 검색으로 종단 확인**

백엔드를 로컬에서 띄우고 스펙의 근거 사례로 확인한다.

```bash
cd backend && source .venv/bin/activate && uvicorn app.main:app --port 8001 &
curl -s -X POST http://localhost:8001/price-jobs -H "Content-Type: application/json" \
  -d '{"wine_name":"베터 하프"}'
# 반환된 job id로 폴링
curl -s http://localhost:8001/price-jobs/<job_id> | python3 -m json.tool | head -40
```

Expected: `price_checked_items`에 `"status": "priced_from_image"`가 최소 1건, 또는
이미지에 가격이 실제로 없으면 `no_price`. (2026-09-03 기준 "베터 하프"는 GS25
결제화면 이미지가 있는 글이 검색된다.)

- [ ] **Step 8: 커밋**

```bash
git add docs/superpowers/specs/2026-09-03-image-price-extraction-design.md
git commit -m "docs: 이미지 가격 추출기 벤치마크 결과 및 채택 기록"
```

---

## Self-Review Notes

- **스펙 커버리지:** 이미지 URL 수집·필터·상한(Task 1) · fetcher 반환 타입 변경(Task 2) ·
  와쌉 이미지/쿠키 실측(Task 3, 스펙이 남긴 미확인 항목) · 채널 단일 확정(Task 4) ·
  Gemini 추출기(Task 5) · OCR 추출기(Task 6) · 다운로드/선택/첫성공 오케스트레이션(Task 7) ·
  본문 0건일 때만 이미지 경로 + `blog_img`/`wassap_img` source_type + `priced_from_image`
  상태(Task 8) · 배선(Task 9) · 프론트 라벨(Task 10) · 벤치마크 지표 5종(Task 11) ·
  채택 결정과 기록(Task 12) — 스펙 항목 전부 대응됨.
- **타입 일관성:** `FetchedBody(text, image_urls)`는 Task 2에서 정의하고 Task 8 테스트에서
  같은 필드명으로 쓴다. 추출기 시그니처 `(image_bytes: bytes, mime_type: str) -> int | None`은
  Task 5·6·7에서 동일하다. `extract_image_price(image_urls) -> int | None`은 Task 8에서
  정의하고 Task 9에서 같은 형태로 주입한다.
- **플레이스홀더 없음:** 모든 단계에 실제 코드·실제 명령이 있다. Task 12의 표 값과 채택
  결정만 실행 결과에 따라 채워지는데, 이는 벤치마크의 산출물이지 미결정 설계가 아니다.
- **기존 테스트 영향:** Task 2에서 `test_collectors.py`의 2건이 `body.text` 비교로 바뀐다
  (교체 코드를 그대로 실었다). Task 8의 `_normalize_body`가 문자열 본문을 계속 받아주므로
  `test_jobs.py`의 기존 가격 job 테스트 6건은 수정 없이 통과한다.
