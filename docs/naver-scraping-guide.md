# 네이버 블로그·카페 스크래핑 가이드

이 저장소(`NARA-APP-Wine-Scrapper`)가 실제로 쓰는 방식을 정리한 문서다. 다른 사람과 다른
Claude 에이전트가 같은 방식을 재사용할 수 있도록, **동작하는 코드 기준**으로 적었다.
(기준 시점 2026-09-09, 구현 위치 `backend/app/collectors.py`, `backend/app/naver_search.py`)

핵심 요약:

| 대상 | 목록 찾기 | 본문 전체 | 로그인 쿠키 |
|---|---|---|---|
| 네이버 블로그 | 공식 Open API (`openapi.naver.com`) | `m.blog.naver.com/{blogId}/{logNo}` HTML | **불필요** |
| 네이버 카페 | 카페 내부 검색 API (`apis.cafe.naver.com`) | 게시글 상세 API (`article.cafe.naver.com`) | **필수** |

카페만 개인 크롬 세션 쿠키가 필요하다. 블로그는 공식 API + 모바일 페이지라 쿠키가 없다.

---

## 1. 네이버 블로그

### 1-1. 목록: 공식 Open API

발급받은 애플리케이션 키로 검색한다. 비공식 크롤링이 아니라 정식 API다.

```
GET https://openapi.naver.com/v1/search/blog.json
헤더: X-Naver-Client-Id, X-Naver-Client-Secret
파라미터: query, display, sort=date
```

- 구현: `backend/app/naver_search.py`의 `search_blog()`
- 응답에 `title` / `description`(스니펫) / `link` / `postdate` / `bloggername`이 다 들어있어
  목록 단계에서 별도 페이지 접근이 필요 없다.
- 429가 오면 최대 2회 지수 백오프 재시도(`_MAX_RETRIES`), 연속 호출 사이 0.3초 간격.
- 썸네일은 API 응답에 없어서 글 본문 페이지에서 따로 긁는다(`_fetch_blog_thumbnail`).

키는 [네이버 개발자센터](https://developers.naver.com)에서 애플리케이션 등록 후 발급.
환경변수 `NAVER_CLIENT_ID` / `NAVER_CLIENT_SECRET`.

### 1-2. 본문: 모바일 페이지를 직접 받는다

검색 API의 `description`은 150자 안팎 스니펫이라 본문 속 정보(가격 등)를 못 잡는다.
본문 전체가 필요하면 **모바일 URL**을 쓴다.

```
GET https://m.blog.naver.com/{blogId}/{logNo}
```

- 구현: `fetch_blog_full_body()`
- **PC URL(`blog.naver.com/PostView.naver`)을 쓰면 안 된다** — iframe 껍데기만 오고 본문이
  없다(`og:image` 정도만 있음). 모바일 페이지는 서버에서 본문을 직접 렌더링해준다.
- 쿠키·특수 헤더 불필요. 공개 글이면 그냥 받아진다.
- 입력 URL에서 `blogId`/`logNo`를 정규식으로 뽑아 모바일 URL로 재조립한다
  (`_BLOG_LINK_RE`).

---

## 2. 네이버 카페

카페는 신형 SPA(`ca-fe.pstatic.net`)라 **서버 HTML에 게시글이 없다**. 옛 엔드포인트
(`ArticleList.nhn`, `ArticleSearchList.nhn`)는 검색어를 무시하거나 빈 응답을 준다
(2026-07-21~22 실측). 그래서 그 SPA가 실제로 호출하는 **내부 XHR API를 직접 부른다.**
엔드포인트와 필수 헤더는 브라우저 devtools + `page.js` 번들에서 확인해 알아냈다(2026-07-23).

### 2-1. cafeId(숫자 ID)를 먼저 알아야 한다

카페 식별자가 **두 개**고 서로 다른 값이다. 자동 변환이 안 되니 수동으로 확인해 넣는다.

| 이름 | 예(와쌉) | 쓰는 곳 |
|---|---|---|
| `cafe_id` (URL 슬러그) | `winerack24` | 게시글 링크 조립 |
| `clubid` | `10050146` | 옛 API |
| `cafe_numeric_id` (신형 `cafeId`) | `20564405` | **내부 검색/상세 API** |

확인 방법: 브라우저에서 그 카페의 신형 화면을 열면 URL이
`cafe.naver.com/f-e/cafes/{cafeId}/menus/0` 형태다 — 이 숫자가 `cafe_numeric_id`.
비어 있으면 `search_wassap()`이 그 소스를 건너뛴다(`backend/app/sources.py` 참고).

### 2-2. 목록: 카페 내부 검색 API

```
GET https://apis.cafe.naver.com/search/v2/cafes/{cafeId}/search/articles
파라미터: query, perPage, page
헤더:
  Cookie: NID_AUT=...; NID_SES=...
  Referer: https://cafe.naver.com/f-e/cafes/{cafeId}/menus/0
  Origin: https://cafe.naver.com
  User-Agent: Mozilla/5.0
  X-Cafe-Product: pc
  X-Cafe-Version: 1.0
  X-Cafe-Phase: real
```

- 구현: `search_wassap()`
- **`X-Cafe-*` 헤더 3개가 없으면 400**이 온다. 빼먹지 말 것.
- 응답 경로: `result.articleList[].item` → `subject`(제목, HTML 태그 포함) /
  `summary`(스니펫) / `articleId` / `addDate` / `thumbnailImageUrl`.
  `entry.type != "ARTICLE"`인 항목(공지·광고 등)은 건너뛴다.
- 게시글 링크는 `https://cafe.naver.com/{cafe_id}/{articleId}`로 조립한다.

### 2-3. 본문: 게시글 상세 API

```
GET https://article.cafe.naver.com/gw/v4/cafes/{cafeId}/articles/{articleId}
파라미터: query=&fromPopular=true&useCafeId=true&requestFrom=A
헤더: 위와 동일 (Referer만 해당 게시글 URL)
```

- 구현: `fetch_wassap_full_body()`
- 응답 경로: `result.article.contentHtml` — Smart Editor 마크업(본문 문단은 `se-text`).
- 2026-08-31 devtools 실측으로 확인한 경로다.

---

## 3. 개인 크롬 세션 키 방식 (카페 전용)

카페 API는 로그인 세션을 요구한다. 공식 API가 없어서, **로그인한 브라우저의 쿠키를 그대로
서버 환경변수에 넣어 쓴다.** 두 값만 필요하다: `NID_AUT`, `NID_SES`.

### 3-1. 쿠키 뽑는 방법

1. 크롬에서 네이버 로그인 상태로 `cafe.naver.com` 접속
2. `F12` → **Application** 탭 → 좌측 **Storage → Cookies → `https://cafe.naver.com`**
   (또는 `naver.com`)
3. `NID_AUT`, `NID_SES` 두 행의 **Value**를 복사
4. 아래 형식으로 한 줄로 합친다 (HTTP `Cookie` 헤더 문법 그대로)

```
NID_AUT=<값>; NID_SES=<값>
```

devtools 대신 Network 탭에서 카페 XHR 요청 하나를 골라 `Cookie` 요청 헤더를 그대로
복사해도 된다(불필요한 쿠키가 섞여도 동작한다).

### 3-2. 넣는 위치

| 환경 | 파일 | 반영 방법 |
|---|---|---|
| 로컬 | `backend/.env` | 프로세스 재시작 (`load_dotenv()`가 시작 시 1회 읽음) |
| 개발서버 | `/var/www/NID/wine-scraper-api/.env` | `systemctl restart wine-scraper-api` |

```
NAVER_COOKIE=NID_AUT=<값>; NID_SES=<값>
```

- 개발서버는 systemd `EnvironmentFile`로 이 `.env`를 읽는다 → **파일만 바꾸면 반영 안 되고
  반드시 서비스 재시작이 필요**하다.
- 이 앱은 기동이 60~90초 걸린다. 재시작 직후 `curl`이 연결 거부되는 건 정상이니
  `until curl -s -o /dev/null http://127.0.0.1:8001/price-history; do sleep 5; done`처럼
  기다린 뒤 확인할 것.
- 파일 소유·권한은 `www-data:www-data 640` 유지(`chown` 확인).

### 3-3. 만료 감지

쿠키는 **주기적으로 만료된다**(수 주 단위, 재로그인·비밀번호 변경 시 즉시). 만료 증상:

```json
{"result":{"errorCode":"0004","reason":"로그인하지 않았습니다.", ...}}
```
HTTP 401. 이 앱에서는 이렇게 나타난다:

- 카페 **본문**만 전부 실패하고 목록/블로그는 정상 → 거의 확실히 쿠키 만료
- 이 저장소 기준: 가격검색 화면의 "검색한 글" 목록에서 와쌉 글이 전부
  `본문 가져오기 실패`(`status = no_body`)로 표시된다
- 예외를 삼키고 그 글만 건너뛰도록 설계돼 있어서 **에러 없이 결과가 조용히 0건이 된다** —
  그래서 로그·화면 상태로 판단해야 한다

빠른 점검 스니펫:

```python
import httpx, os
r = httpx.get(
    "https://article.cafe.naver.com/gw/v4/cafes/20564405/articles/369625",
    params={"query": "", "fromPopular": "true", "useCafeId": "true", "requestFrom": "A"},
    headers={
        "Cookie": os.environ["NAVER_COOKIE"],
        "Referer": "https://cafe.naver.com/winerack24/369625",
        "Origin": "https://cafe.naver.com",
        "User-Agent": "Mozilla/5.0",
        "X-Cafe-Product": "pc", "X-Cafe-Version": "1.0", "X-Cafe-Phase": "real",
    }, timeout=15,
)
print(r.status_code, r.text[:200])   # 401 + errorCode 0004 이면 쿠키 만료
```

### 3-4. 보안·운영 주의

- **개인 로그인 세션이다.** 이 값이 유출되면 그 네이버 계정으로 로그인된 상태가 넘어간다.
  Git에 커밋 금지(`.env`는 `.gitignore`), 채팅·이슈·PR 본문에 붙여넣지 말 것.
- 에이전트에게 갱신을 맡길 때도 값 자체를 대화에 붙이면 세션 기록에 남는다. 서버에
  직접 넣고 "넣었다"고만 알려주는 방식이 안전하다.
- 공용 계정 하나로 운영하는 편이 낫다(개인 계정을 쓰면 그 사람이 재로그인할 때마다 깨진다).
- 호출 간격을 두고 소량만 쓴다 — 비공식 API라 과도한 호출은 차단 사유가 된다.
  이 앱은 검색당 카페 글 10건 상한(`max_items=10`).

---

## 4. HTML → 텍스트 변환 시 걸러야 하는 것들

본문 HTML을 그대로 텍스트로 바꾸면 **본문이 아닌 것들이 섞여 오탐을 만든다**.
`_html_to_lines()`가 순서대로 제거·처리한다(전부 실측으로 하나씩 추가된 것들):

1. `<script>` / `<style>` — 태그+내용 통째로. 안 지우면 JS/CSS 텍스트가 본문으로 새어
   들어온다.
2. **링크카드(`se-oglink-title` / `se-oglink-summary` / `se-oglink-url`)** —
   이건 이 글이 아니라 **다른 글**의 제목·요약이다. 안 지우면 그 글의 내용이 이 글
   내용으로 잡힌다(실측: 링크카드의 "3만 원 이상 20% 할인" → 이 글의 가격으로 오저장).
3. 블록 태그(`</p>`, `<br>`, `</div>`) → 줄바꿈으로 치환 후 남은 태그 제거,
   HTML 엔티티 복원(`&#x3D;` 등 Smart Editor에 흔함).
4. **표(`<table>`)** — 셀마다 별개의 줄이 되면서 "채널명 4칸 / 가격 4칸" 같은 구조에서
   짝을 잃는다. `_table_lines()`가 표를 **행 방향·열 방향 양쪽으로** 이어붙인 줄을
   추가해, 머리글이 어느 방향이든 짝이 한 줄에 오게 만든다.
5. 이미지 URL은 따로 뽑되(`extract_image_urls`) 본문 사진이 아닌 것은 제외 —
   프로필(`blogpfthumb`), 링크카드 썸네일(`dthumb`), 정적 아이콘, `.gif` 스티커.

---

## 5. 실패 처리 원칙

이 저장소가 지키는 규칙이고, 재사용할 때도 같이 가져가면 좋다.

- **개별 실패는 그 항목만 건너뛴다.** 본문 fetch 실패·파싱 실패·저장 실패가 전체 수집을
  중단시키지 않는다(`try/except` 후 `return None`).
- **지어내지 않는다.** 근거가 애매하면 버린다. 예: 채널을 특정할 수 없으면 저장 안 함,
  검색어가 글에 없으면 그 글의 정보를 검색어에 붙이지 않음.
- **왜 안 나왔는지 화면에 남긴다.** 결과 0건과 "실패해서 0건"을 사용자가 구분할 수
  있어야 한다(이 앱은 글마다 `가격 추출` / `가격 언급 없음` / `제외 — 검색어 없는 글` /
  `본문 가져오기 실패`를 표시).

---

## 6. 다른 에이전트를 위한 요점

- 카페 관련 문제는 **먼저 쿠키 만료를 의심**할 것(401 `errorCode 0004`). 코드를 고치기 전에
  확인.
- 블로그 본문이 비어 있으면 **PC URL을 쓰고 있는지** 확인. `m.blog.naver.com`이어야 한다.
- 카페 400 오류는 **`X-Cafe-*` 헤더 누락**이 대표 원인.
- 카페 `cafeId`는 `clubid`와 다른 값이다. 자동 변환 시도하지 말고 브라우저 URL에서 확인.
- 비공식 API라 언제든 바뀔 수 있다. 바뀌면 브라우저 devtools Network 탭에서 실제 XHR을
  다시 확인하는 게 가장 빠르다 — 이 문서의 엔드포인트도 그렇게 알아냈다.
