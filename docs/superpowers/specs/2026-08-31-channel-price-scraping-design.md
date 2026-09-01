# a5 와인정보 스크래퍼 — 채널별 가격 수집 설계 (2026-08-31)

## 배경

"a5 와인정보 스크래퍼"(`index.html` + `js/app.js` + `backend/app/`)는 사용자가 와인명을
검색하면 뉴스·매거진/네이버 블로그/유튜브/와쌉카페/해외소스를 온디맨드로 수집해
보여준다. 여기에 "이 와인이 채널별로 얼마에 팔리는지"를 보여주는 가격 정보를
추가한다 — 네이버 블로그와 와쌉카페 게시글 본문에 종종 등장하는 "이마트 7월
29,800원~33,000원" 같은 가격 언급을 수집해 채널별로 정리해서 보여준다.

## 목표

- 검색 시 블로그·와쌉카페에서 채널별 가격을 함께 수집한다.
- 가격은 DB에 채널·년월 단위로 누적 저장해, 나중에 시세 추이를 조회할 수 있는
  기반을 만든다(이번 스펙은 조회 UI 자체는 만들지 않음 — 저장까지만).
- 검색 결과 화면에 "가격" 섹션을 새로 추가해 이번 검색에서 찾은 채널별 가격을
  보여준다.

## 범위

- 이 스펙은 **a5 온디맨드 검색(`index.html`/`js/app.js`/`backend/app/`)**만
  다룬다. `wine-briefing/`(데일리 브리핑 크론)은 무관하다.
- 가격 추출은 **정규식 패턴 매칭**으로, 본문 텍스트(se-text)에 직접 타이핑된
  가격만 대상으로 한다(LLM 미사용 — 사용자 확정, 비용 없지만 표현이 다양한
  글은 놓칠 수 있음을 감수). 와쌉 게시글 중 일부는 가격이 CU픽업주문 위젯처럼
  구조화된 임베드 컴포넌트나 스크린샷 이미지로만 표시되는 경우가 있는데,
  이런 위젯/이미지 안의 가격은 이번 범위 밖 — 실사용해보고 놓치는 비중이
  크면 위젯 JSON 파싱이나 OCR/LLM 추가를 후속으로 검토한다.
- 과거 축적된 가격을 보여주는 "가격 이력 조회" 화면은 이번 범위 밖 — DB에는
  전부 쌓이니 나중에 별도 스펙으로 만들 수 있다.
- 이 스펙은 UI 시각 디자인(표 색상/레이아웃 디테일)을 다루지 않는다 — 기존
  `.result-group`/`.ds-table` 스타일을 그대로 따른다.

## 전제 조건 — DB 접근 (해결됨)

`backend/.env`의 `wine_info_app` 계정이 2026-08-13 전체 계정 재구성으로 폐기되어
인증 실패가 났었다(`NARA-Information-Digest/docs/CREDENTIALS.local.md` 참고,
`wine_info_app`→`DB_ID_MARKETING`로 컷오버됨). `.env`를 `DB_ID_MARKETING` 계정으로
갱신해 접속 확인 완료 — `wine_info` 스키마에 ALL PRIVILEGES 보유, 신규 테이블
생성·INSERT·SELECT 전부 가능.

## 데이터 모델

신규 테이블 `wine_channel_prices` — 한 소스에서 채취한 가격 = 한 행:

```sql
CREATE TABLE wine_channel_prices (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    wine_query VARCHAR(255) NOT NULL,      -- 검색에 사용한 와인명 (예: "몬테스 알파")
    channel VARCHAR(50) NOT NULL,          -- 채널 표준명 (아래 채널 목록의 정식 명칭)
    price_low INT NOT NULL,                -- 원 단위, 범위 없으면 price_high와 동일
    price_high INT NOT NULL,
    year_month CHAR(7) NOT NULL,           -- 'YYYY-MM' — 본문에 월 언급 있으면 그 값, 없으면 게시글 발행년월
    source_type VARCHAR(20) NOT NULL,      -- 'blog' | 'wassap'
    source_url VARCHAR(500) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_wine_channel_month (wine_query, channel, year_month)
);
```

`wine_articles`와 달리 브랜드 매칭(`wine_article_brands`)은 쓰지 않는다 —
`wine_query`(검색어 그대로)로 충분하고, 기존 브랜드 매칭 로직을 재사용할
근거가 없다(가격 언급은 특정 SKU가 아니라 브랜드/제품명 단위로 뭉뚱그려
언급되는 경우가 많음).

## 채널 목록 (정식 명칭 + 매칭용 별칭)

| 그룹 | 정식 명칭 | 매칭 별칭 |
|---|---|---|
| 마트 | 이마트 | 이마트, 이마트몰 |
| 마트 | 코스트코 | 코스트코, 코스트코 홀세일 |
| 마트 | 트레이더스 | 트레이더스, 트레이더스 홀세일 |
| 마트 | 롯데마트 | 롯데마트 |
| 편의점 | CU | CU, 씨유 |
| 편의점 | GS25 | GS25, 지에스25, 지에스 25 |
| 편의점 | 이마트24 | 이마트24, 이마트 24, E24 |
| 편의점 | 세븐일레븐 | 세븐일레븐, 세븐일레븐앱, 7-11, 세븐일레븐24 |
| 특판 | 새마을구판장 | 새마을구판장, 새마을 구판장 |
| 특판 | 조양마트 | 조양마트 |
| 특판 | 레드셀러 | 레드셀러 |
| 와인샵 | 와인픽스 | 와인픽스 |
| 와인샵 | 에노테카 | 에노테카 |
| 와인샵 | 와인앤모어 | 와인앤모어, 와인 앤 모어 |

(사용자 원문의 "e24"는 이마트24로 정규화. 별칭 목록은 초안이며 오탐/누락 보고
받으면 계속 보강.)

## 아키텍처

```
기존 흐름: POST /jobs → run_job()이 news/blog/youtube/wassap/international 수집
                       → GET /jobs/{id} 폴링 → 프론트 카드 렌더링

신규 추가:
run_job() 안에서 blog/wassap 수집이 끝난 뒤(각 수집기가 이미 찾은 게시글 목록 재사용):
  1. fetch_full_body(post)  — 신규
     - 블로그: m.blog.naver.com/{blogId}/{logNo} 모바일 페이지 직접 fetch,
       본문 영역 텍스트 추출 (iframe 문제 없음)
     - 와쌉: `GET https://article.cafe.naver.com/gw/v4/cafes/{cafe_numeric_id}/articles/{article_id}?query=&fromPopular=true&useCafeId=true&requestFrom=A`
       (2026-08-31 브라우저 devtools로 실측 확인) 호출 → 응답
       `result.article.contentHtml`이 본문 HTML(Smart Editor 마크업, `se-text`
       컴포넌트 안에 실제 문단 텍스트). 이 HTML을 태그 벗겨(`_strip_tags` 재사용)
       평문으로 만든다. CU픽업주문류 위젯이나 이미지 안에 박힌 가격은 이 방식으로
       못 잡음(범위 참고) — se-text 문단에 직접 타이핑된 가격만 대상.
  2. extract_channel_prices(body_text) -> list[{channel, price_low, price_high, year_month}]  — 신규
     - 채널 별칭이 등장하는 문장/줄 안에서 가격 패턴(`\d{1,3}(,\d{3})*\s*원`) 탐색
     - 숫자 2개(범위 표시자 `~`/`-`/`부터`~`까지`로 연결) → price_low/high,
       숫자 1개 → price_low = price_high
     - 같은 줄/인접 문맥에 "N월" 있으면 그 달, 없으면 게시글 발행일의 년월
  3. 찾은 항목마다 wine_channel_prices에 INSERT (DB 저장 = 소스 단위, 병합 없음)
  4. 이번 검색에서 찾은 항목들을 채널별로 그룹핑해 min(price_low)~max(price_high)로
     합치고, 소스 링크는 해당 채널로 찾은 모든 source_url을 리스트로 모아
     새 응답 필드 price_results로 GET /jobs/{id}에 포함
```

**본문 가져오기 실패(요청 실패/파싱 실패)는 그 게시글만 건너뛰고 계속 진행** —
기존 수집기들의 "개별 실패 허용" 원칙과 동일.

## API 응답 변경

`GET /jobs/{id}`에 새 필드 추가(기존 `results` 배열은 그대로 유지):

```json
{
  "status": "...", "total": N, "done": N,
  "results": [ ... 기존과 동일 ... ],
  "price_results": [
    {
      "channel": "이마트",
      "price_low": 29800,
      "price_high": 33000,
      "year_month": "2026-07",
      "source_urls": ["https://blog.naver.com/...", "https://cafe.naver.com/..."]
    }
  ]
}
```

`price_results`는 채널당 최대 1개 항목(이미 min~max로 합쳐진 상태) — 채널에
값이 없으면 배열에 아예 없음. 같은 채널을 찾은 소스들의 `year_month`가 서로
다르면(드문 경우) 가장 최근 년월을 대표값으로 쓴다 — 가격은 최신 정보가
더 중요하기 때문.

## 프론트엔드

- `js/app.js`의 `RESULT_CATEGORY_META`(현재 news→blog→youtube→wassap→international
  순서)에 `price`("가격")를 **news와 blog 사이**에 추가.
- 기존 카테고리는 전부 `buildResultCard`(썸네일/제목/발췌 카드) 공용 템플릿을
  쓰지만, 가격은 표 형태라 **전용 렌더 함수**(`buildPriceTable(price_results)`)를
  새로 만든다 — 기존 `.ds-table` 클래스(디자인 시스템 정본 표 스타일) 사용.
  컬럼: 채널 | 가격 | 년월 | 출처. 출처 컬럼엔 소스 링크를 순서대로 나열(예:
  `[출처1] [출처2]`).
- `price_results`가 비어 있으면(이번 검색에서 가격 언급 없음) 가격 섹션 자체를
  숨긴다 — 기존 카테고리들의 "결과 없으면 그룹 숨김" 패턴과 동일.

## 에러 처리

- 본문 fetch 실패, 정규식 매칭 0건, DB insert 실패 — 전부 "그 게시글/그 채널만
  생략, 나머지는 계속" 원칙. 지어내지 않는다.
- DB insert 실패는 로그만 남기고 `price_results` 응답 자체는 그 회차에 실제로
  찾은 값 기준으로 정상 반환(DB 저장 실패가 화면 표시까지 막지 않음).

## 테스트 계획

- `extract_channel_prices()`: 순수 함수라 유닛테스트로 커버 — 정상 매칭(범위/단일가),
  월 언급 있음/없음, 채널 별칭 여러 개, 채널·가격 언급 없는 일반 텍스트(빈 리스트
  반환) 케이스.
- 채널별 min~max 병합 로직: 같은 채널 여러 소스 → 범위로 합쳐지는지, 소스 링크
  전부 나열되는지 유닛테스트.
- 본문 fetch(`fetch_full_body`)는 실제 네이버 페이지 구조에 의존 — 유닛테스트로
  커버 불가, 배포 후 수동 검증(기존 관례와 동일).
- DB insert/조회는 **DB 접근 문제가 해결된 뒤** 수동 E2E 검증.

## 범위 밖 (후속 작업)

- 가격 이력(시계열) 조회 UI
- LLM 기반 가격 추출로 업그레이드(정규식 한계 드러나면)
- 채널 별칭 목록 보강(오탐/누락 실사용 피드백 반영)
