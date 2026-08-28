# 해외 소스 스크래핑 확장 + 브라우저 자동화 전환 설계 (2026-08-28)

## 배경

`wine-briefing/scrape.py`의 `scrape_international()`이 매일 로컬 PC에서 해외 매거진·통계
소스를 urllib 직접 fetch + 정규식으로 수집한다. `docs/scraping-sources.md`의 "해외·통계·
이벤트 소스" 표를 보면 시도했던 23개 소스 중 6개만 수집 중이고, 나머지 20개는 다음 이유로
막혀 있다:

- **JS 클라이언트 렌더링**: James Suckling, Wine Business, Harpers, World of Fine Wine,
  Robb Report, Imbibe Magazine, Vinography, Palate Press, Snooth, VinePair, Punch —
  정적 HTML에 목록이 없어 정규식으로 못 뽑음.
- **강한 봇차단/페이월**: Wine Enthusiast, Wine-Searcher, Jancis Robinson, Wine Advocate,
  Vinous, GuildSomm, Bloomberg, Financial Times — 403 또는 회원제.

이 중 상당수(Wine Enthusiast, Jancis Robinson, Wine Business, GuildSomm, Vinous 등)는
와인 업계에서 공신력이 높은 매체라 그대로 두기 아깝다. 또한 산업 통계·트렌드 리포트
(IWSR, SVB, Liv-ex 등)는 애초에 목록에 없었다.

## 목표

1. 막혀서 미수집인 20개 소스를 브라우저 자동화(JS 렌더링)로 재시도해 되살린다.
2. 지금 목록에 없는 산업 통계/트렌드 소스(IWSR, SVB, Liv-ex)를 추가한다.
3. 정규식 기반 파싱을 LLM 기반 파싱으로 바꿔, 사이트 레이아웃이 바뀌어도 깨지지 않게 한다.
4. 이미 검증된 6개 기존 소스(Decanter, Wine Spectator, OIV, Drinks Business, Wine
   Industry Advisor, 1WineDude)는 손대지 않는다 — 이미 안정적으로 도는 경로.

## 범위

- `wine-briefing/scrape.py`의 해외 소스 수집 부분만 다룬다.
- 국내 소스(네이버 뉴스/블로그/와쌉/유튜브), 이벤트, 국내 통계, 전방 시장 TODO는
  이 스펙 밖 — 필요하면 별도 스펙.
- 실제 GPT computer-use처럼 스크린샷 보고 클릭(쿠키배너 닫기, "더보기" 클릭 등)하는
  무거운 에이전트 루프는 채택하지 않는다 — 비용·시간 문제로 라이트 방식(렌더링 + 텍스트
  추출 + 저렴한 LLM 파싱 1회)으로 확정.

## 새 소스 목록

### 되살릴 기존 실패 소스 (20개, 전부 재시도)

| 소스 | 기존 실패 사유 |
|---|---|
| James Suckling | Next.js 클라이언트 렌더링 |
| Wine Business | 검색결과 클라이언트 렌더링 |
| Harpers | 검색결과 클라이언트 렌더링 |
| World of Fine Wine | 검색결과 클라이언트 렌더링 |
| Robb Report | 검색결과 클라이언트 렌더링 |
| Imbibe Magazine | 결과 목록 클라이언트 렌더링 |
| Vinography | 결과 목록 클라이언트 렌더링 |
| Palate Press | 검색 무관 고정 위젯(진짜 검색 아님) |
| Snooth | 결과 목록 클라이언트 렌더링 |
| VinePair | 404 (불안정 접근) |
| Punch | 검색 결과 0건 (다른 검색 방식 필요) |
| Wine Enthusiast | 403 차단 |
| Wine-Searcher | 403 차단 |
| Jancis Robinson | 403 차단 |
| Wine Advocate | 유료 구독, 정적 HTML에 목록 없음 |
| Vinous | 유료 구독 사이트, 검색이 홈으로 리다이렉트 |
| GuildSomm | 회원제 콘텐츠 |
| Bloomberg | 강한 봇차단(403) |
| Financial Times | 페이월 + 봇차단(403) |
| Investopedia | 402, 와인 전문 매체 아님(우선순위 낮음이나 시도는 포함) |

강한 봇차단/페이월 소스(Bloomberg, FT, Wine Advocate, Vinous, GuildSomm 등)는 브라우저
자동화로도 안 뚫릴 가능성이 높다 — 그래도 시도하고, 안 되면 기존 원칙대로 조용히
생략한다(범위에서 빼지 않음, 결과로 판단).

### 신규 산업 통계/트렌드 소스 (3개)

`docs/scraping-sources.md`의 빈 "## 트렌드" 섹션에 채운다.

| 소스 | URL | 비고 |
|---|---|---|
| IWSR Insight | https://www.theiwsr.com/insight/ | Wine Intelligence를 인수해 흡수됨 |
| SVB State of the US Wine Industry | https://www.svb.com/trends-insights/reports/wine-report | 연 1회 발행(주로 1월) — 대부분 날짜엔 결과 없음, 정상 |
| Liv-ex 블로그 | https://www.liv-ex.com/blog-fine-wine-market-insights-and-analysis/ | 파인와인 시장 데이터/트렌드 |

## 아키텍처

```
scrape_international()
  ├─ 기존 6개 소스 — urllib + 정규식 (그대로 유지, 미변경)
  │    Decanter, Wine Spectator, OIV, Drinks Business, Wine Industry Advisor, 1WineDude
  │
  └─ scrape_international_browser()  (신규)
       23개 소스(되살릴 20 + 신규 3) 대상, 사이트마다:
       1. Playwright headless Chromium으로 페이지 방문, JS 렌더링 완료까지 대기(타임아웃 15초)
       2. 렌더링된 본문에서 뉴스 목록 영역 텍스트 추출 (~3000자로 자름)
       3. Gemini(`gemini-flash-latest`, 무료 티어) 1회 호출로 파싱
          — backend/app/briefing_summary.py의 call_gemini()와 동일한 REST 호출 패턴 재사용
          — 프롬프트: "이 텍스트에서 최근 기사 최대 3개의 title/url/summary를 JSON으로"
       4. 파싱 결과를 title_ko/summary_ko로 번역(기존 translate_to_ko() 재사용)해
          foreign_magazines 또는 foreign_stats 리스트에 append
       사이트 사이 1~2초 딜레이. 사이트별 실패는 그 사이트만 스킵.
```

클릭·스크린샷 기반 인터랙션은 없다(라이트 방식). 쿠키배너·로그인월로 본문이 가려지는
사이트는 여전히 실패할 수 있음 — 감수하는 트레이드오프.

**API 키**: `backend/.env`의 `GEMINI_API_KEY`를 그대로 읽는다(같은 로컬 저장소 안이라
바로 접근 가능 — 서버로 옮기거나 새로 발급받을 필요 없음).

**실행 위치**: 로컬 PC, 기존 `scrape.py` 크론(평일 09:00)과 같은 프로세스 안에서 순차 실행.

**의존성**: `pip install playwright && playwright install chromium` 1회 설치 필요
(로컬 Mac, 브라우저 바이너리 약 300MB).

## 데이터 모델

기존 `international.json` 스키마(`foreign_magazines`/`foreign_stats` 리스트, 각 항목
`source`/`title`/`title_ko`/`summary_ko`/`url`/`date`)를 그대로 재사용 — 스키마 변경 없음.

## 문서 갱신

`docs/scraping-sources.md`:
- "해외·통계·이벤트 소스" 표의 ❌ 20개 항목 상태를 실행 결과에 따라 ✅/❌로 갱신
- 빈 "## 트렌드" 섹션에 IWSR/SVB/Liv-ex 표 추가
- "실행 방식" 설명에 브라우저 자동화(Playwright+Gemini) 경로 추가

## 에러 처리

- Playwright 페이지 로드 타임아웃(15초) → 스킵, 로그에 사유 기록
- Gemini 호출 실패/quota 초과 → 스킵(그 사이트만, 다른 사이트는 계속 진행)
- 모델 응답이 JSON 파싱 안 되는 경우 → 빈 리스트로 처리, 스킵
- "수집 실패/항목 없음 = 그냥 생략, 지어내지 않는다" 기존 원칙을 브라우저 경로에도 동일 적용

## 테스트 계획

- Gemini 응답에서 JSON을 뽑아내는 파싱 함수에 대해 assert 기반 self-check 하나
  (정상 JSON 응답 케이스, 코드블록으로 감싼 응답 케이스, 깨진/빈 응답 케이스 — 마지막
  경우 빈 리스트 반환 확인)
- 실제 사이트 크롤링(Playwright 렌더링 성공 여부, 사이트별 봇차단 통과 여부)은 네트워크·
  사이트 상태 의존적이라 자동테스트로 커버 불가 — 배포 후 로컬에서 수동 실행해 로그로
  사이트별 성공/실패 확인(기존 관례와 동일)

## 범위 밖 (후속 작업)

- 이벤트(와인21/WSA/도운), 국내 통계, 전방 시장 TODO 소스 자동화
- Vision 기반 클릭 자동화(쿠키배너 닫기, 페이지네이션 등)
- 봇차단 우회 고도화(스텔스 플러그인, 프록시 로테이션 등)
