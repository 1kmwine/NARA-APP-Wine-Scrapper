# a5 와인정보 스크래퍼 — 이미지 속 가격 추출 설계 (2026-09-03)

## 배경

`2026-08-31-channel-price-scraping-design.md`로 만든 가격검색은 게시글 **본문 텍스트에
직접 타이핑된** 채널명+가격만 정규식으로 잡는다. 그 스펙 자체가 한계를 명시해뒀다 —
"위젯/이미지 안의 가격은 이번 범위 밖 — 실사용해보고 놓치는 비중이 크면 OCR/LLM
추가를 후속으로 검토한다". 이 스펙이 그 후속이다.

실사용에서 놓치는 게 확인됐다(2026-09-03, "베터 하프" 검색):

- 검색된 블로그·와쌉 글 5건 전부 `가격 언급 없음`으로 처리 → 가격 이력 0건
- 그중 와쌉 글 "GS25 오늘의 와인 - 베터하프 문의"(`cafe.naver.com/winerack24/367941`)는
  본문에 가격 텍스트가 없고, **첨부된 결제화면 캡처 이미지 안에** 총 상품 금액
  19,900원 / 할인 -3,980원 / 최종 결제 금액 15,920원이 찍혀 있다.

즉 "가격이 없는 글"이 아니라 "가격이 이미지에만 있는 글"인데 0건으로 떨어지고 있다.

## 목표

본문 텍스트에서 가격을 못 찾은 글에 한해, 글에 첨부된 이미지에서 가격을 읽어
기존 채널별 가격 저장 흐름에 합류시킨다.

## 결정 사항

- **추출 방식**: Gemini Vision과 Tesseract OCR **둘 다 구현하고 실측 비교 후 결정**
  (사용자 확정). 판단 기준은 **인식률**과 **rate limit**. 벤치마크 결과가 나오기
  전까지는 어느 쪽도 기본값으로 확정하지 않는다.
- **대상 범위**: 본문 정규식이 가격을 **0건** 낸 글만 (사용자 확정). 본문에서 이미
  가격을 찾은 글은 이미지를 보지 않는다 — 호출 수를 최소화하고, 같은
  `(source_url, channel, year_month)` 유니크 키에 텍스트 값과 이미지 값이 충돌하는
  상황도 자연히 피한다.
- **저장 값**: 결제화면처럼 금액이 여러 개면 **최종 결제금액**(위 예시의 15,920원)
  (사용자 확정). 소비자가 실제로 지불한 값이 채널별 시세 비교에 가장 현실적이다.
- **채널 판정**: 채널명은 **이미지가 아니라 글 제목/본문 문맥**에서 기존
  `CHANNEL_ALIASES`로 확정한다. 이미지 모델이 채널을 지어내지 못하게 하기 위함 —
  기존 가격 추출의 "지어내지 않음(애매하면 놓치는 쪽)" 원칙을 그대로 유지한다.
  채널을 확정 못 하면 가격을 읽었더라도 저장하지 않는다.

## 범위

- 대상은 a5 온디맨드 가격검색(`backend/app/`, 가격검색 탭)만. `wine-briefing/`
  (데일리 브리핑 크론)은 무관하다.
- 와쌉의 CU픽업주문 같은 **구조화된 임베드 위젯 JSON 파싱은 범위 밖** — 이번엔
  이미지(비트맵)만 다룬다.
- 가격 이력 화면(가격검색 탭 UI) 자체는 이미 있다. 이 스펙은 그 화면에 들어갈
  데이터의 출처를 하나 늘리는 것이고, 상태 표시 한 줄(`priced_from_image`)만 추가한다.

## 아키텍처

```
run_price_job (기존)
  └ 글마다 _collect_prices()
       ├ 본문 텍스트 → extract_channel_prices()  … 기존 정규식
       │     └ 1건 이상 → 저장하고 끝 (이미지 안 봄)
       └ 0건이면 ↓ (이번 스펙)
            ├ extract_image_urls(html)          … 글 HTML에서 <img> 수집·필터·상한
            ├ 이미지 다운로드 (httpx)
            ├ extract_final_price(bytes, mime)  … 추출기 인터페이스 (2종 중 택1)
            │     ├ price_image_gemini.py       … Gemini Vision (REST)
            │     └ price_image_ocr.py          … Tesseract OCR
            └ 채널은 글 제목/본문에서 CHANNEL_ALIASES로 확정 → insert_channel_price()
```

## 컴포넌트

### 1. 이미지 URL 수집 — `backend/app/collectors.py`

`_html_to_lines()`가 태그를 벗기면서 `<img>`까지 같이 버리고 있다. 태그를 벗기기
**전에** URL을 뽑는 함수를 추가한다.

```python
def extract_image_urls(html_str: str, limit: int = 5) -> list[str]
```

필터(2026-09-03 실측 — 블로그 글 1건에 `<img>` 11개 중 본문 사진은 8개):

| 제외 대상 | 판별 |
|---|---|
| 작성자 프로필 썸네일 | `blogpfthumb-phinf` 도메인 |
| 외부 링크 카드 썸네일 | `dthumb-phinf` 도메인 |
| 이모티콘·아이콘 | `ssl.pstatic.net/static`, `.gif` |

남은 것 중 앞에서부터 `limit`(기본 5)장까지만. 상한을 두는 이유는 호출 수와
소요 시간 상한을 보장하기 위함 — 한 글에 사진 30장인 후기 글이 흔하다.

`fetch_blog_full_body()` / `fetch_wassap_full_body()`는 지금 본문 텍스트만
돌려주는데, 이미지 URL도 같이 돌려주도록 반환 타입을 바꾼다:

```python
class FetchedBody(NamedTuple):
    text: str
    image_urls: list[str]
```

`run_price_job`에 주입되는 `fetch_blog_body`/`fetch_wassap_body` 콜러블 시그니처와
`main.py`의 배선도 같이 바뀐다(호출부는 두 곳뿐).

> 와쌉 게시글 상세 API 응답(`contentHtml`)에도 `<img>`가 같은 형태로 들어있는지는
> 구현 첫 단계에서 실제 응답으로 확인한다(블로그는 2026-09-03 확인 완료 —
> `mblogthumb-phinf.pstatic.net`, 인증 없이 다운로드 가능). 카페 이미지 CDN이
> 쿠키를 요구하면 기존 `NAVER_COOKIE`를 다운로드에도 붙인다.

### 2. 추출기 인터페이스

두 구현이 같은 시그니처를 갖는다:

```python
def extract_final_price(image_bytes: bytes, mime_type: str) -> int | None
```

값을 못 읽으면 `None`. "지어내지 않음" 원칙 — 애매하면 `None`.

**`backend/app/price_image_gemini.py`**

기존 `briefing_summary.call_gemini()` 패턴을 그대로 따른다(httpx REST,
`gemini-flash-latest`, `responseMimeType=application/json`). 이 레포는
`google-genai` SDK를 안 쓰고 REST로만 호출하므로 새 의존성이 없다.
모델 기본값이 `-latest` 별칭인 이유도 그대로다 — 이 API 키 무료 티어는 버전
고정 모델이 quota=0이다.

이미지는 `inlineData`(base64)로 싣고, 프롬프트는 결제화면/행사 배너에서
**최종 결제금액 한 개**만 뽑도록 지시한다. 응답 스키마:

```json
{"final_price": 15920, "label": "최종 결제 금액"}
```

가격이 안 보이면 `{"final_price": null, "label": null}`.

**`backend/app/price_image_ocr.py`**

`pytesseract` + `tesseract-ocr-kor`. OCR 텍스트에서 기존
`price_extraction._PRICE_RE`를 재사용해 숫자를 뽑고, "최종 결제/결제 금액/총
결제" 라벨과 같은 줄이거나 바로 다음 줄인 값을 우선한다. 라벨을 못 찾으면
`None`(가장 큰 숫자를 찍는 식의 추측을 하지 않는다).

서버에 `tesseract-ocr`, `tesseract-ocr-kor` 패키지 설치가 필요하다 —
벤치마크에서 이쪽이 채택될 경우에만 설치한다.

### 3. 벤치마크 — `scripts/bench_image_price.py`

두 추출기를 실제 이미지로 비교해 채택을 결정한다.

- **샘플 수집**: 가격검색을 몇 개 와인으로 돌려 `no_price`로 떨어진 글들의
  이미지를 `data/bench_images/`에 내려받는다(스크립트의 `--collect` 모드).
- **정답 라벨**: 사람이(또는 Claude가 이미지를 직접 보고) 각 이미지의 최종
  결제금액을 `data/bench_images/labels.json`에 적는다. 가격이 없는 이미지는
  `null`로 라벨해 오탐(있지도 않은 가격을 만들어내는 경우)도 측정한다.
- **측정 지표**:

| 지표 | 의미 |
|---|---|
| 정답률 | 라벨과 정확히 일치한 비율 |
| 오탐률 | 라벨이 `null`인데 값을 뱉은 비율 (가장 위험 — 없는 가격을 저장하게 됨) |
| 미검출률 | 라벨에 값이 있는데 `None`을 낸 비율 |
| 평균 소요 | 이미지 1장당 초 |
| 실패 수 | 429/503/타임아웃 등 호출 실패 건수 |

- **출력**: 두 추출기 결과를 나란히 표로 출력. 이 표를 근거로 채택을 정하고,
  결정 내용을 이 스펙 문서 하단에 "채택 결과" 절로 덧붙인다.

### 4. 파이프라인 연결 — `backend/app/jobs.py`

`_collect_prices()`가 `no_price`를 반환하던 자리에서 이미지 추출을 시도한다.

1. 글 HTML에서 뽑아둔 `image_urls`를 순회하며 다운로드 → `extract_final_price()`
2. 값이 나오면 채널을 `f"{title}\n{body_text}"`에서 `CHANNEL_ALIASES`로 찾는다
   - 채널이 정확히 하나면 그 채널로 저장
   - 0개거나 2개 이상이면 **저장하지 않는다**(어느 채널 가격인지 확정 불가)
3. `year_month`는 기존과 동일하게 글 발행일 기준
4. `source_type`은 `blog_img` / `wassap_img` (기존 `blog`/`wassap`와 구분,
   `VARCHAR(20)`에 들어감)
5. 한 글에서 여러 이미지가 값을 내면 **첫 성공 값 하나만** 쓰고 나머지 이미지는
   보지 않는다(결제화면이 여러 장이면 같은 값이 중복 저장되는 걸 막고 호출도 아낌)

반환 상태에 `priced_from_image`를 추가한다 — 프론트 '검색한 글' 목록의
가격추출 칸에 "이미지에서 추출"로 표시된다.

## 에러 처리

- 이미지 다운로드 실패(404/타임아웃): 그 이미지만 스킵, 다음 이미지로.
- Gemini 429/503: 그 이미지만 스킵하고 로그. 검색 전체는 계속 — 기존
  `_collect_prices`의 `except Exception` 방침과 같다. 무료 티어 특성상
  429/503이 드물지 않다(2026-09-03 페어링 블록에서 `gemini-flash-latest` 503
  반복 관측).
- OCR 예외(언어팩 미설치 등): 그 이미지만 스킵, 로그.
- 어느 경우든 **이미 저장된 텍스트 기반 가격에는 영향 없음**.

## 테스트

기존 `backend/tests/test_price_extraction.py` 스타일(순수 함수 단위 테스트)을 따른다.

- `extract_image_urls()` — 프로필/외부링크/이모티콘 제외, 상한 적용, 순서 보존
- `price_image_gemini.extract_final_price()` — httpx 목으로 응답 파싱, `null`
  응답 시 `None`, HTTP 에러 시 예외 전파 안 하고 `None`
- `price_image_ocr.extract_final_price()` — pytesseract 목으로 OCR 텍스트 주입,
  라벨 있는 값 우선, 라벨 없으면 `None`
- `jobs` 통합 — 본문 가격 0건일 때만 이미지 경로를 타는지, 채널 0개/2개일 때
  저장 안 하는지 (기존 job 테스트 패턴 사용)

실제 인식 정확도는 단위 테스트가 아니라 벤치마크 스크립트가 책임진다.

## Task 3 실측 결과 (2026-09-03)

`backend/.env`의 `NAVER_COOKIE`가 만료돼 있다 — 오늘 스크랩된 실제 article ID
(`361790`, `367941` 등)로도 `article.cafe.naver.com` 호출이 전부 401
(`errorCode 0004, 로그인하지 않았습니다`)을 낸다. 와쌉 이미지가 실제로
쿠키 없이 받아지는지는 그래서 이번엔 확인 못 함 — 코드는 어차피
`download_image(url, client, cookie=...)`로 쿠키를 선택적으로 흘려보내게
짜여 있어 이 결정을 막지 않는다. 쿠키 갱신 후 재확인 필요.

## 범위 밖

- 위젯(CU픽업주문 등) JSON 파싱
- 이미지에서 채널명 읽기 — 채널은 글 텍스트에서만 확정
- 이미지 캐싱/재사용 (같은 글을 재검색하면 다시 내려받고 다시 호출)
- 한 글에서 여러 채널 가격을 이미지로 동시에 잡기
