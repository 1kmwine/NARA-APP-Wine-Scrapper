# NARA-APP-Wine-Scrapper
와인에 대한 정보를 웹에서 모으는 도구

## 로컬 실행

**프런트엔드**(정적 파일):
```bash
python3 -m http.server 8935
```

**백엔드**(FastAPI):
```bash
cd backend
python3.11 -m venv .venv && source .venv/bin/activate
# 주의: 그냥 python3는 이 개발 환경에서 3.14로 해석되어, 이 프로젝트가 고정한
# 의존성 일부의 프리빌트 wheel이 없다(설치 실패 또는 소스 빌드 필요). 반드시
# python3.11(또는 3.11.x)로 venv를 만들 것.
pip install -r requirements-dev.txt
cp .env.example .env  # DB_PASSWORD/NAVER_CLIENT_ID/NAVER_CLIENT_SECRET/GITHUB_TOKEN/NAVER_COOKIE 채우기
uvicorn app.main:app --reload --port 8001
```

**테스트**:
```bash
cd backend && source .venv/bin/activate && pytest -v
```

## 소스 설정 (scraping-sources.md)

스크래퍼가 검색할 소스 목록은 하드코딩돼 있지 않고, 매 `POST /jobs` 호출마다
`docs/scraping-sources.md`(GitHub Contents API, 30초 캐싱)를 읽어 결정된다.
`POST /sources`로 새 소스를 추가하면 그 파일에 커밋된다. `GET /sources`는 현재
등록된 소스 카운트/이름을 조회 전용으로 반환한다(프런트의 검색 화면 문구와
"소스 데이터 추가" 패널의 "등록된 소스" 목록이 이 엔드포인트를 쓴다). 상세
포맷은 `docs/scraping-sources.md` 자체의 안내를 참고.

주의: `NAVER_COOKIE`(와쌉 수집용)와 `GITHUB_TOKEN`은 만료/회전될 수 있다 — 갱신
절차는 `docs/scraping-sources.md`의 "쿠키 갱신 가이드" 참고.
