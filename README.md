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
cp .env.example .env  # DB_PASSWORD/NAVER_CLIENT_ID/NAVER_CLIENT_SECRET 채우기
uvicorn app.main:app --reload --port 8001
```

**테스트**:
```bash
cd backend && source .venv/bin/activate && pytest -v
```
