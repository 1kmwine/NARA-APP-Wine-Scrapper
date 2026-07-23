# 스크래핑 소스 목록

> 마지막 업데이트: 2026-06-19
> 용도별 구분: **[브리핑]** = 데일리 브리핑 수집, **[와인]** = 와인 상세 스크래퍼, **[공통]** = 둘 다

> [!note] 향후 integrated_item_info 통합 대상
> 여기 나열된 소스(유튜브·인스타그램·네이버 블로그·네이버 카페·해외 저널 등)는 향후
> `wine_info.integrated_item_info` 테이블(ERP+1KM 조인 결과)에 흡수될 예정이다.
> 통합 구조는 `NARA-Information-Digest` 리포의 `docs/SOURCE-DATA-ARCHITECTURE.md` 참고.

---

## 아키텍처 — 수집은 전부 로컬, 발송만 CCR

2026-06-17 구조 변경. **Anthropic API를 로컬에서 쓰지 않는다.** 수집·HTML 생성은 로컬 PC에서 순수 Python(urllib)으로 처리하고, 클라우드(CCR)는 완성된 HTML을 받아 이메일만 발송한다.

| 단계 | 실행 위치 | 방식 | 비고 |
|------|----------|------|------|
| ① 소스 수집 | **로컬 PC** `~/WINE-BRIEFING/scrape.py` | Python urllib + 세션 쿠키 | 네이버/IG 쿠키·로컬 IP 필수 |
| ② 브리핑 HTML 생성 | **로컬 PC** `scrape.py` | 어제 JSON과 비교해 중복 제거 후 HTML 생성 | 수집 직후 같은 스크립트에서 처리 |
| ③ GitHub 업로드 | **로컬 PC** `scrape.py` | GitHub Contents API | `docs/data/{날짜}/*.json` + `docs/briefings/{날짜}.html` |
| ④ 이메일 발송 | **CCR(클라우드)** 트리거 | GitHub에서 HTML 다운로드 → Gmail API | 수집 일절 안 함 |

> [!danger] CCR에서 수집 금지
> 와쌉·블로그·유튜브·인스타·네이버 뉴스검색은 **네이버/유튜브/인스타그램 세션 쿠키와 로컬 PC IP**에 의존한다. CCR(클라우드 IP)에서 이들을 호출하면 **즉시 IP 차단**된다. 따라서 ①~③은 반드시 로컬, ④만 CCR.

> **실행 위치**: `~/WINE-BRIEFING/`
> **수집·생성 스크립트**: `~/WINE-BRIEFING/scrape.py` (이 문서를 읽고 시작 — 아래 "스크립트 동작" 참고)
> **실행 스크립트**: `~/WINE-BRIEFING/run.sh` (crontab: `0 9 * * 1-5`)
> **로그**: `~/WINE-BRIEFING/briefing.log`
> **쿠키·토큰**: `scrape.py` 상단 상수 (`NAVER_COOKIE`, `IG_COOKIE`, `GH_TOKEN`)
> **GitHub 업로드 경로**: `1kmwine/NARA-WINEINFO/docs/data/{날짜}/*.json`, `docs/briefings/{날짜}.html`
> **CCR 발송 트리거**: `나라셀라-브리핑-실제메일-0600` (평일 06:00 KST)

---

## 스크립트 동작 (scrape.py)

`scrape.py`는 실행 시 **가장 먼저 이 문서(`~/NARA-WINEINFO/docs/scraping-sources.md`)를 읽어** 아래 항목을 파싱한 뒤 수집을 시작한다. 문서를 수정하면 스크립트 동작이 바뀐다.

스크립트가 이 문서에서 읽어가는 설정 (파싱 대상):
- **유튜브 채널** — `## 유튜브` 표의 `youtube.com/@핸들` 과 `Channel ID`
- **인스타그램 계정** — `## 인스타그램` 표의 `instagram.com/계정`
- **국내 뉴스·매거진** — `## 국내 뉴스·매거진` 표의 검색어
- **뉴스룸 직접 수집** — `## 뉴스룸` 표의 URL·방식
- **검색 쿼리** — 아래 `수집 쿼리` 블록

```수집쿼리
와쌉_clubid: 10050146
블로그_검색어: 와인 시음 후기, 와인 추천, 와인 페어링, 와인 구매 추천
뉴스_토픽검색어: 와인 수입, 내추럴와인, 샴페인, 와인 트렌드, 와인 행사, 주류 수입동향, 관세청 주류
최근_뉴스_일수: 3
최근_블로그_일수: 14
최근_유튜브_일수: 7
최근_인스타_일수: 7
```

---

## 국내 뉴스·매거진 **[브리핑]**

> **실행 위치: 로컬 PC** · **수집 방식: 네이버 뉴스검색 (urllib + NID 쿠키)**
> `search.naver.com?where=news&query=와인 {검색어}&sort=1` → 제목·언론사·요약(snippet)·날짜 파싱.
> 언론사명이 대상 매체와 일치하거나, 제목에 와인 키워드가 있으면 채택. 최근 N일 이내만.
> ⚠️ 네이버 쿠키·로컬 IP 의존 → CCR 수집 불가.

| 매체 | 분류 | 검색어 | URL |
|------|------|--------|-----|
| 소믈리에타임즈 | 매거진 | 소믈리에타임즈 | https://www.sommeliertimes.com/ |
| 와인21 | 매거진 | 와인21 | https://www.wine21.com/11_news/news_list.html |
| 한국경제 | 뉴스 | 한국경제 와인 | https://www.hankyung.com/ |
| 매일경제 | 뉴스 | 매일경제 와인 | https://www.mk.co.kr/ |
| 조선비즈 | 뉴스 | 조선비즈 와인 | https://biz.chosun.com/ |
| 세계일보 | 뉴스 | 세계일보 와인 | https://www.segye.com/ |
| 메트로신문 | 뉴스 | 메트로 와인 | https://www.metroseoul.co.kr/ |
| 파이낸셜뉴스 | 뉴스 | 파이낸셜뉴스 와인 | https://www.fnnews.com/ |

---

## 뉴스룸 **[브리핑]**

> **실행 위치: 로컬 PC** · **수집 방식: 직접 fetch (urllib)**
> board = 그누보드 게시판 HTML 파싱 / wp = WordPress REST API(`/wp-json/wp/v2/posts`).

| 매체 | URL | 방식 |
|------|-----|------|
| 나라셀라 칼럼 | https://www.naracellar.com/bbs/board.php?bo_table=column | board |
| 나라셀라 보도자료 | https://www.naracellar.com/bbs/board.php?bo_table=press | board |
| 와인인 | https://winein.co.kr/wp-json/wp/v2/posts?per_page=8&_fields=title,link,date,excerpt | wp |

> [!note] 에노테카·신세계엘앤비 뉴스룸
> 에노테카(`enoteca.co.kr/News`)는 imweb 기반으로 게시판이 상품·브랜드 페이지 위주라 일간 뉴스 추출이 불안정 → **현재 미수집**. 신세계 엘앤비 뉴스룸도 동일 사유 미수집. 추후 RSS/API 확인 시 추가.

---

## 유튜브 **[브리핑]**

> **실행 위치: 로컬 PC** · **수집 방식: YouTube InnerTube `ytInitialData` 파싱 (urllib)**
> `youtube.com/channel/{ID}/videos` 페이지의 `ytInitialData` JSON에서 최신 영상 최대 3개/채널.
> Channel ID 미상이면 `youtube.com/@핸들` 페이지에서 `"channelId"` 자동 추출. 최근 N일 이내만.
> 채널 외 영상 포함 금지.

| 채널명 | URL | Channel ID |
|--------|-----|-----------|
| 비밀이야 | https://www.youtube.com/@bimirya | UCaKQ7_GT0k8u_sL0nE2tgkA |
| 양갱 | https://www.youtube.com/@yanggangtv | UCohsv4KNeRzmj7E6ipE8COA |
| 와인킹 | https://www.youtube.com/@wineking | UCb7KNFvMuvQz9LPRK4xyzfA |
| 와인 좀 한해 | https://www.youtube.com/@JUNGHANHAE | UCsTjitDbkUW20H3U20ITqaw |
| 이민정 MJ | https://www.youtube.com/@Rheeminjung_MJ | UCFNUGAiaGRgzVCXrjVoe1Hw |
| 와지트 WAZIT | https://www.youtube.com/@wazitwine | UCfFi7-7_41KLVYHJtZ_wbrg |
| 장르가 머니 | https://www.youtube.com/@genreismoney | UCn7WoT17_HlpfOPQHEqgUkw |
| 술술워커 | https://www.youtube.com/@술술워커soolsoolworker | UCoGMA51Q6Sb6_rc6gfm67fA |
| 비노이스타 Vinoista | https://www.youtube.com/@vinoista2019 | UCho-kNWD5gnMRwh5hSWjofg |
| 세상의 모든 와인 | https://www.youtube.com/@allthatwine | UCTFjxmJVbIr-bqjyFkmdMAw |
| 김박사의 와인랩 | https://www.youtube.com/@DrKimsWineLab | UCoXVH3jniR0Jtt1K0Z6pZSg |

> 2026-06-24 추가: 위 5개(와지트~세상의 모든 와인)는 사용자 제공 영상에서 채널 역추적. 김박사의 와인랩은 구독자 약 2.6만명 확인되어 추가(10,000명 이상 기준). 레코드와인·저스트드링크·와푸밸은 채널 핸들·구독자 수 검증 불가로 보류 — TODO: @담당자 확인 필요.

---

<!--
## 인스타그램 **[브리핑]** — 2026-06-23부터 비활성화 (사용자 요청)

> **실행 위치: 로컬 PC** · **수집 방식: Instagram Private API (urllib + sessionid 쿠키)**
> `GET /api/v1/users/web_profile_info/?username={username}` → user ID → `GET /api/v1/feed/user/{uid}/?count=12`.
> 최근 N일 이내 게시물만. 캡션·좋아요·경과일 수집.
> ⚠️ sessionid 만료 시 전 계정 403. 쿠키: `scrape.py` `IG_COOKIE`.
> 갱신: Chrome → instagram.com 로그인 → F12 → Application → Cookies → sessionid 복사.

재활성화 시 이 주석(`<!-- -->`) 을 해제하고 아래를 다시 파이프 테이블(`|...|...|`)로 되돌릴 것.
계정 목록 (참고용):
- naracellar https://www.instagram.com/naracellar/ 나라셀라
- wineandmoressg https://www.instagram.com/wineandmoressg/ 와인앤모어
- ayoungfbc https://www.instagram.com/ayoungfbc/ 아영FBC
- iihida https://www.instagram.com/iihida/ 비닛
- moment_event2025 https://www.instagram.com/moment_event2025/ 와인행사모음
-->

---

## 커뮤니티

### 와쌉 (네이버 카페) **[브리핑]**

> **실행 위치: 로컬 PC** · **수집 방식: apis.cafe.naver.com 검색 API + NID_AUT/NID_SES 쿠키**
> "★와쌉★ 와인 싸게 사는 사람들" — 한국 최대 와인 소비자 커뮤니티 (17.5만 회원). clubid: 10050146.
> 신형 카페(SPA)라 `ArticleSearchList.nhn` 등 구 API는 검색이 안 됨(2026-07-22 확인) —
> `GET https://apis.cafe.naver.com/search/v2/cafes/{cafeId}/search/articles?query=&perPage=&page=`
> (요청 헤더에 `X-Cafe-Product: pc` / `X-Cafe-Version: 1.0` / `X-Cafe-Phase: real` 필요, 없으면 400)
> 를 검색어로 직접 호출한다 — `subject`(제목)/`summary`(스니펫, `<b>` 하이라이트 포함)/
> `thumbnailImageUrl`(썸네일)이 한 번에 옴. **cafeId는 clubid와 다른 별도 숫자**라(winerack24
> 기준 cafeId 20564405) 새 카페 등록 시 브라우저로 `cafe.naver.com/f-e/cafes/{cafeId}/...`
> 열어서 URL의 숫자를 직접 확인해야 한다.

- https://cafe.naver.com/winerack24 (clubid: 10050146, cafeId: 20564405)

### 네이버 블로그 (와인 시음/구매 후기) **[공통]**

> **실행 위치: 로컬 PC** · **수집 방식: urllib + NID 쿠키 (와쌉과 동일 쿠키)**
> `search.naver.com?where=blog&query={검색어}&sort=1` → 제목·요약·날짜 파싱.
> **최근 N일 이내만 채택** (오래된 글 제외). 검색어는 위 `수집 쿼리` 블록 참조.

### 티스토리 와인 블로그 **[브리핑]**

> [!note] 현재 미수집
> 기존엔 WebSearch로 수집했으나 로컬 전환 후 Anthropic API 미사용 → 미수집. 추후 티스토리 검색 API/직접 크롤링 확인 시 추가.

---

## 와인 수입 통계 **[브리핑]**

> **실행 위치: 로컬 PC** · **수집 방식: 뉴스 키워드 검색 (일간) + 월간 수동 확인**

### 일간 수집 — 뉴스 검색으로 커버

`수집쿼리`의 `뉴스_토픽검색어`에 `주류 수입동향`, `관세청 주류`를 포함하여, 수입 관련 언론 기사를 매일 자동 수집한다.

### 월간 원시 데이터 — 수동 확인

관세청 수출입무역통계(tradedata.go.kr)는 WAF(웹방화벽)로 직접 API 호출 차단됨. 월 1회 수동으로 확인한다.

| 항목 | 내용 |
|------|------|
| URL | https://tradedata.go.kr/ |
| 메뉴 경로 | 수출입 통계 → 수출입 실적 → HS 코드 기준 조회 |
| HS 코드 | **220421** (2L 이하 용기 포도주), **220410** (발포성 포도주) |
| 수집 주기 | 월 1회 (매월 15일 이후 전월 확정치 발표) |
| 확인 담당 | TODO: @담당자 지정 필요 |

> [!note] 자동화 가능성
> `data.go.kr` 공공데이터포털의 관세청 무역통계 API(`https://unipass.customs.go.kr:38010/ext/rest/`)는 인증키 발급 후 사용 가능. 향후 인증키 발급 시 `scrape.py`에 `scrape_trade_stats()` 함수로 추가 예정.

---

## 해외·통계·이벤트 소스 **[브리핑]** — 2026-06-26부터 로컬 직접 수집으로 전환

> **실행 위치: 로컬 PC** · **수집 방식: urllib 직접 fetch + 무료 Google Translate 엔드포인트로 한국어 번역**
> CCR(클라우드)은 usage credits 미설정으로 실행 자체가 막혀(2026-06-24~25 전부 실패) **사용 중단(홀드)**.
> `scrape.py`의 `scrape_international()`이 `docs/data/{날짜}/international.json`을 직접 생성·업로드.
> 제목·요약을 영문으로 수집한 뒤 `translate_to_ko()`로 한국어 번역 (`title_ko`, `summary_ko` 필드) — 브리핑 HTML엔 번역본만 표시.
> ⛔ 수집 실패/항목 없음 = 그냥 생략. 지어내지 않는다.

| 소스 | 상태 | URL | 비고 |
|------|------|-----|------|
| Decanter | ✅ 수집 중 | https://www.decanter.com/wine-news/ | 제목+부제(synopsis) 페어링, 개별 기사 URL 매칭 불안정해 목록 페이지로 링크 |
| Wine Spectator | ✅ 수집 중 | https://www.winespectator.com/ | 홈페이지에서 제목+부제(dek) 추출, 개별 기사 URL 정확히 매칭됨 |
| OIV | ✅ 수집 중 | https://www.oiv.int/news/press | 제목+URL 안정적 매칭, 부제 없음 |
| James Suckling | ❌ 수집 불가 | https://www.jamessuckling.com/ | Next.js 클라이언트 렌더링 — 정적 HTML에 콘텐츠 없음 |
| VinePair | ❌ 수집 불가 | https://vinepair.com/ | 요청 시 404 (안정적 접근 불가) |
| Wine Enthusiast | ❌ 수집 불가 | https://www.wineenthusiast.com/ | 403 차단 |
| Wine-Searcher | ❌ 수집 불가 | https://www.wine-searcher.com/ | 403 차단 |
| Wine Advocate | ❌ 미확인 | https://winejournal.robertparker.com/ | TODO: @담당자 접근 가능 여부 확인 필요 |

| 소스군 | 항목 | 상태 |
|--------|------|------|
| 국내 통계 | 가처분소득, 가구 주류소비, 소비심리, 비닛 차트 | 미수집 (월간 갱신, 안정적 파싱 소스 미확보) — TODO |
| 이벤트 | 와인21 이벤트, WSA, 도운 | 미수집 (페이지 구조상 정규식 매칭 불안정) — TODO |
| 전방 시장 | 유통산업 통계, 외식 트렌드(diaryr), 식품-서울대 | 미수집 — TODO |

> [!note] CCR 트리거
> 트리거명: `나라셀라-해외통계-수집` · 평일 05:30 KST (이메일 발송 트리거보다 먼저 실행) · `docs/scraping-sources.md`를 GitHub에서 직접 읽어 위 표 기준으로 수집.
> 수집 실패/데이터 없음 시 **지어내지 않고 해당 항목 생략** — 추측 금지 원칙 적용.

---

## 쿠키 갱신 가이드

네이버 쿠키(와쌉·블로그·뉴스검색)와 인스타그램 sessionid는 **주기적으로 만료**된다. 수집 실패(403) 시 갱신 후 `scrape.py` 상단 상수 업데이트.

| 쿠키 | 사이트 | 갱신 절차 | scrape.py 상수 |
|------|--------|----------|---------------|
| NID_AUT, NID_SES | naver.com | Chrome → naver.com 로그인 → F12 → Application → Cookies → 값 복사 | `NAVER_COOKIE` |
| sessionid | instagram.com | Chrome → instagram.com 로그인 → F12 → Application → Cookies → sessionid 복사 | `IG_COOKIE` |

---

## 스크래퍼 소스 코드 매핑

| 소스 유형 | 위치 | 실행 | 수집 방식 |
|-----------|------|------|----------|
| 전체 수집 + HTML 생성 | `~/WINE-BRIEFING/scrape.py` | 로컬, 평일 09:00 crontab | 순수 Python urllib (Anthropic API 미사용) |
| 와쌉 카페 | scrape.py `scrape_wassap()` | 로컬 | urllib + 네이버 쿠키 (iframe_url EUC-KR + 검색) |
| 네이버 블로그 | scrape.py `scrape_blog()` | 로컬 | urllib + 네이버 쿠키, 최근 N일 필터 |
| 국내 뉴스·매거진 | scrape.py `scrape_news()` | 로컬 | 네이버 뉴스검색 + 쿠키, 언론사/제목 필터 |
| 뉴스룸 | scrape.py `scrape_newsroom()` | 로컬 | board.php 파싱 / WP REST API |
| 유튜브 | scrape.py `scrape_youtube()` | 로컬 | InnerTube ytInitialData (5채널) |
| 인스타그램 | scrape.py `scrape_instagram()` | 로컬 | Instagram API + sessionid |
| 와인 수입 통계 (뉴스) | scrape.py `scrape_news()` (토픽: 주류 수입동향, 관세청 주류) | 로컬 | 뉴스 키워드 검색 |
| 이메일 발송 | CCR 트리거 `naracellar-wine-briefing-send` | 클라우드, 평일 06:00 (전날 데이터 발송) | GitHub 최신 HTML → Gmail API |
