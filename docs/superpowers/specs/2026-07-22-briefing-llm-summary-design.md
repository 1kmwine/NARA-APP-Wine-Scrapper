# 주간 브리핑 LLM 요약 — 설계

## 배경

데일리 브리핑 탭의 주간 요약은 현재 프론트(`js/app.js`)에서 그 주 아이템 제목을 그대로 발췌해 붙이는 방식이다(`buildCategoryProse`). 실제로 글을 "읽고" 요약하는 게 아니라 제목 나열에 가깝다. 이 문서는 그 자리를 실제 LLM(Claude) 호출로 대체하는 백엔드 기능을 설계한다.

## 목표

- 그 주(월~일) `docs/data/{date}/*.json` 원본을 모아 Claude에게 실제로 읽혀서, 글로벌 동향/소비자 동향/수입사 주요 활동 3분류로 **현황만** 서술하는 요약을 생성한다(대응 방향·추천 문장 없음 — 기존 프론트 요구사항 유지).
- 같은 주는 반복 요청해도 LLM을 다시 부르지 않도록 캐싱한다.
- 캐시를 `docs/summaries/`에 파일로 남겨 `docs/data`/`docs/briefings`와 같은 커밋 이력 패턴을 따른다.

## 비목표

- 일별("오늘의 요약") 히어로 요약 — 지금처럼 프론트 발췌 방식 유지.
- 브랜드 매칭/DB 연동 — 이 기능은 `docs/data` JSON만 읽고 사내망 MySQL은 건드리지 않는다.
- 과거 주 재생성 — fingerprint가 같으면 영구 캐시, 강제 재생성 API는 범위 밖.

## 아키텍처

```
프론트(app.js) --GET /briefings/weekly-summary?week_start=YYYY-MM-DD--> FastAPI(main.py)
                                                                              |
                                              docs/summaries/{week_start}.json 존재 +
                                              fingerprint 일치?
                                                yes -> 그대로 반환
                                                no  -> docs/data/{7일}/*.json 로드
                                                       -> 6개 source_category를 3버킷으로 그룹핑
                                                          (global=international,
                                                           consumer=youtube+wassap+blog,
                                                           importer=news+newsroom)
                                                       -> Claude API 호출(버킷별 현황 요약)
                                                       -> 응답 JSON 파싱
                                                       -> 캐시 파일 기록
                                                       -> git add+commit+push
                                                       -> 응답 반환
```

신규 모듈 2개, `main.py`엔 라우터만 얇게 추가:

- `backend/app/briefing_summary.py` — 데이터 로드, 버킷 그룹핑, fingerprint 계산/비교, 캐시 읽기/쓰기, 프롬프트 빌더. 대부분 순수 함수.
- `backend/app/llm_client.py` — Claude API 래퍼(요청 조립, 응답 JSON 파싱, malformed 시 1회 재시도).
- `backend/app/git_publish.py` — `docs/summaries/{week_start}.json` add+commit+push를 담당하는 얇은 subprocess 래퍼. 파일 내용이 기존과 동일하면 커밋 생략.

## 카테고리 매핑

프론트 [js/app.js](../../../js/app.js)의 `SUMMARY_CATEGORIES`와 동일한 매핑을 백엔드에서도 그대로 쓴다(프론트-백엔드 카테고리 정의가 벌어지지 않도록 이 표가 단일 기준):

| 버킷 | key | 포함 source_category |
|---|---|---|
| 글로벌 동향 | `global` | `international` |
| 소비자 동향 | `consumer` | `youtube`, `wassap`, `blog` |
| 수입사 주요 활동 | `importer` | `news`, `newsroom` |

## fingerprint (캐시 무효화)

캐시 파일에 그 주 7일치 각 날짜별 `(존재 여부, 6개 카테고리 파일별 항목 수 합)` 튜플 목록을 `fingerprint` 필드로 같이 저장한다. 재요청 시 현재 `docs/data` 상태로 다시 계산한 fingerprint와 비교해서:

- 같으면 캐시 그대로 반환(LLM 재호출 없음).
- 다르면(예: 진행 중인 주에 오늘 파일이 새로 생김) 재생성.

지난 주처럼 더 이상 파일이 늘지 않는 주는 fingerprint가 고정되므로 최초 1회만 LLM을 호출하고 이후 영구 캐시 히트.

한 주 데이터가 통째로 없으면(모든 날짜 파일 없음) LLM 호출을 생략하고 각 버킷 summary를 "이번 주 수집된 소식 없음"으로 채워 반환한다.

## API 계약

```
GET /briefings/weekly-summary?week_start=YYYY-MM-DD
```

- `week_start`는 반드시 월요일 날짜(프론트 `getWeekStart()`와 동일 규칙). 아니면 400.

성공 응답 (200):

```json
{
  "week_start": "2026-07-20",
  "week_end": "2026-07-26",
  "generated_at": "2026-07-22T09:00:00+09:00",
  "cached": true,
  "categories": [
    {"key": "global", "title": "글로벌 동향", "item_count": 21, "summary": "..."},
    {"key": "consumer", "title": "소비자 동향", "item_count": 38, "summary": "..."},
    {"key": "importer", "title": "수입사 주요 활동", "item_count": 24, "summary": "..."}
  ]
}
```

에러:

- `400` — `week_start` 형식 오류 또는 월요일이 아님.
- `502` — LLM 호출 실패(재시도 포함 최종 실패). `detail`에 원인 메시지.

## 프롬프트 설계

버킷별로 그 주 수집 항목의 `title`(+있으면 `excerpt`/`snippet`, 각 80자 컷)을 모아 Claude에 전달하되, 버킷당 최대 40건까지만 포함한다(그 이상이면 최신순으로 40건 자르고, 잘렸다는 사실과 전체 건수는 프롬프트에 같이 알려줘서 "총 N건 중 최근 40건 기준"이라는 걸 모델이 인지하게 한다) — 실측 데이터에서 소비자 버킷이 주당 30~40건대라 토큰 예산 초과를 막기 위한 안전장치. 시스템 프롬프트 핵심 제약:

- "지금 상황을 사실 위주로 서술하라. 대응 방향, 제안, 추천 문장은 쓰지 마라." (기존 프론트 요구사항과 동일)
- 응답은 반드시 지정된 JSON 스키마(`{"global": "...", "consumer": "...", "importer": "..."}`)로만 반환하도록 지시.
- 버킷에 항목이 하나도 없으면 해당 필드는 호출 없이 서버에서 "이번 주 수집된 소식 없음"으로 채움(프롬프트에 안 넣음).

## 캐시 + git 자동화

- 파일 경로: `docs/summaries/{week_start}.json` (`week_start`, `week_end`, `generated_at`, `fingerprint`, `categories` 포함 — API 응답과 거의 동일하되 `fingerprint` 필드가 추가된 내부 표현).
- 새로 계산한 파일 바이트가 기존과 동일하면 git 작업 자체를 생략.
- 동시 요청 대비 `week_start`별 락(프로세스 내 `threading.Lock` dict)으로 LLM 중복 호출·중복 커밋 방지. **단일 uvicorn 워커 프로세스 배포를 전제한다** — 멀티 워커/멀티 인스턴스로 늘리면 이 락은 프로세스마다 따로 놀아 무력화된다(지금 `main.py`가 이미 싱글 프로세스 전제로 짜여 있어 이 기능도 같은 전제를 따름).
- `git add docs/summaries/{week_start}.json && git commit -m "summary: {week_start} 주간 브리핑 요약" && git push origin main`을 요청 처리 동기 흐름 안에서 실행.
- **push 실패 시**(네트워크 등) 사용자 응답은 정상 반환하고 에러는 로그만 남긴다. 재시도 로직 없음 — 로컬 커밋은 이미 존재하므로 다음 동일 주 요청은 fingerprint가 같아 재생성 없이 캐시를 그대로 쓰고, 이 경우 로컬이 원격보다 앞선 상태가 남을 수 있다(수동 push로 해결). **사용자가 이 트레이드오프를 확인하고 승인함.**
- **주의 (blast radius)**: 이 엔드포인트는 호출될 때마다(캐시 미스 시) `origin/main`에 자동 push한다. 웹 요청 하나가 공유 저장소 상태를 바꾸는 구조 — 사용자가 명시적으로 요청한 설계이며, 배포 전 반드시 이 동작을 인지하고 있어야 한다.

## 에러 처리

- LLM 타임아웃/API 에러 → 502. **프론트는 이미 갖고 있는 `docs/data` raw item으로 기존 발췌 요약(`buildCategoryProse`)에 즉시 폴백** — LLM 요약 실패 시 사용자에게는 발췌 요약이 보임(빈 화면 없음).
- LLM이 스키마에 안 맞는 응답을 주면 더 엄격한 지시로 1회만 재시도, 그래도 실패하면 502.
- `docs/data`에 특정 날짜 파일이 없으면 그 날짜는 빈 것으로 취급(기존 프론트 동작과 동일).

## 설정

`backend/app/config.py`의 `Settings`에 `anthropic_api_key: str` 필드 추가, `.env`/`.env.example`에 `ANTHROPIC_API_KEY` 추가. 기존 DB/네이버 키와 동일하게 필수값(`os.environ[...]`, 없으면 서버 기동 실패) — 기존 패턴을 그대로 따른다.

## 프론트 변경

`js/app.js`의 `renderWeeklySummary()`가 지금은 로컬에서 `buildCategoryProse(items)`로 즉시 렌더링하는데, 이를 다음으로 바꾼다:

1. 렌더링 시작 시 각 버킷에 스켈레톤/로딩 상태 표시.
2. `GET {API_BASE}/briefings/weekly-summary?week_start=...` 호출.
3. 성공하면 응답의 `categories[].summary`로 교체.
4. 실패(네트워크 에러/502)하면 기존 `buildCategoryProse(items)` 결과로 폴백하고, 폴백 중임을 시각적으로 표시하지 않음(사용자 입장에선 그냥 요약 — 실패를 노출할 필요 없음).

`buildCategoryProse`는 삭제하지 않고 폴백 경로로 계속 사용한다.

## 테스트

- `tests/test_briefing_summary.py`: 버킷 그룹핑, fingerprint 계산/비교(같음→캐시 히트, 다름→재생성), 빈 주 스킵 경로, 프롬프트 빌더 — 전부 순수 함수, LLM/git 호출 없이 테스트.
- `llm_client`/`git_publish` 호출은 각각 별도 함수로 분리해 테스트에서 monkeypatch로 대체(anthropic SDK, `subprocess` 실제 실행 없음).
- `tests/test_main.py`에 `/briefings/weekly-summary` 라우터 테스트 추가(캐시 히트/미스, 400, 502 경로) — 기존 테스트 패턴을 따라 `briefing_summary`/`llm_client`/`git_publish`를 monkeypatch.
