from __future__ import annotations
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path

import httpx

# backend/app/briefing_summary.py -> parents[2] == 저장소 루트
REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "docs" / "data"
SUMMARIES_DIR = REPO_ROOT / "docs" / "summaries"

# 프론트(js/app.js SUMMARY_CATEGORIES)와 동일한 버킷 매핑 — 여기서 벌어지면
# 카드 개수/문구가 서로 안 맞게 된다.
BUCKETS = [
    {"key": "global", "title": "글로벌 동향", "match": ("international",)},
    {"key": "consumer", "title": "소비자 트렌드", "match": ("youtube", "wassap", "blog")},
    {"key": "importer", "title": "업계 활동", "match": ("news", "newsroom")},
]

MAX_ITEMS_PER_BUCKET = 40  # 버킷당 실측 주 30~40건대라 토큰 예산 안전장치
MAX_TITLE_LEN = 60


def _load_json(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _entry(title: str, source: str = "") -> dict | None:
    title = (title or "").strip()
    if not title:
        return None
    return {"title": title, "source": (source or "").strip()}


def _entries_from_simple_list(items, source_field: str = "press") -> list[dict]:
    """news/newsroom/wassap/blog 공통 — title(+있으면 press/source)."""
    entries = []
    for it in items or []:
        e = _entry(it.get("title"), it.get(source_field) or it.get("source") or "")
        if e:
            entries.append(e)
    return entries


def _entries_from_youtube(data) -> list[dict]:
    entries = []
    for channel, videos in (data or {}).items():
        entries.extend(e for v in (videos or []) if (e := _entry(v.get("title"), channel)))
    return entries


def _entries_from_international(data) -> list[dict]:
    entries = []
    for key in ("foreign_magazines", "foreign_stats", "domestic_stats", "events", "downstream_market"):
        for it in (data or {}).get(key) or []:
            e = _entry(it.get("title_ko") or it.get("title"), it.get("source") or "")
            if e:
                entries.append(e)
    return entries


def _week_dates(week_start: str) -> list[str]:
    start = datetime.strptime(week_start, "%Y-%m-%d").date()
    return [(start + timedelta(days=i)).isoformat() for i in range(7)]


def load_week_entries_by_category(week_start: str) -> dict[str, list[dict]]:
    """그 주(월~일) docs/data/{date}/*.json에서 카테고리별 {title, source} 목록을
    모은다(source: 언론사/채널명/해외소스명 — 반복되는 저널/채널을 짚어주기 위함).
    파일이 없는 날짜(미래거나 아직 안 쌓인 날)는 그냥 건너뛴다."""
    result = {"news": [], "newsroom": [], "wassap": [], "blog": [], "youtube": [], "international": []}
    for day in _week_dates(week_start):
        day_dir = DATA_DIR / day
        if not day_dir.is_dir():
            continue
        result["news"].extend(_entries_from_simple_list(_load_json(day_dir / "news.json")))
        result["newsroom"].extend(_entries_from_simple_list(_load_json(day_dir / "newsroom.json")))
        result["wassap"].extend(_entries_from_simple_list(_load_json(day_dir / "wassap.json")))
        result["blog"].extend(_entries_from_simple_list(_load_json(day_dir / "blog.json")))
        result["youtube"].extend(_entries_from_youtube(_load_json(day_dir / "youtube.json")))
        result["international"].extend(_entries_from_international(_load_json(day_dir / "international.json")))
    return result


def bucket_entries(entries_by_category: dict[str, list[dict]]) -> dict[str, list[dict]]:
    return {
        b["key"]: [e for cat in b["match"] for e in entries_by_category.get(cat, [])]
        for b in BUCKETS
    }


def compute_fingerprint(entries_by_category: dict[str, list[dict]]) -> str:
    """그 주 원본 데이터가 바뀌었는지 감지하는 용도 — 정확한 내용 비교는 필요
    없고(진행 중인 주에 새 날짜가 추가되는 것만 감지하면 됨) 카테고리별 건수만
    본다."""
    counts = {cat: len(entries) for cat, entries in sorted(entries_by_category.items())}
    return hashlib.sha256(json.dumps(counts, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def _truncate(text: str, limit: int = MAX_TITLE_LEN) -> str:
    return text if len(text) <= limit else text[:limit] + "…"


def build_prompt(bucket_entries_map: dict[str, list[dict]]) -> str:
    sections = []
    for b in BUCKETS:
        entries = bucket_entries_map.get(b["key"], [])
        if not entries:
            continue
        sample = entries[:MAX_ITEMS_PER_BUCKET]
        note = (
            f"(전체 {len(entries)}건 중 최근 {len(sample)}건만 표시)"
            if len(entries) > len(sample) else f"(총 {len(entries)}건)"
        )
        lines = "\n".join(
            f"- {_truncate(e['title'])}" + (f" [{e['source']}]" if e["source"] else "")
            for e in sample
        )
        sections.append(f"## {b['title']} {note}\n{lines}")

    return f"""아래는 나라셀라 와인 수입사가 이번 주 수집한 뉴스/커뮤니티/유튜브/블로그/해외소스
제목 목록이다. 각 줄 끝 [ ]는 언론사·채널·소스명이다.

카테고리별로 이번 주 가장 눈에 띄거나 화제가 된 것 2개를 골라, 각각 짧은 한 줄
문구로 적어라. "와인", "추천", "정보", "후기", "맛집"처럼 어디에나 붙는 일반
단어 하나만 쓰지 말고, 브랜드명·인물명·지역명·행사명 같은 구체적인 고유명사가
들어간 문구로 써라. 완결된 문장(주어+서술어)일 필요는 없지만, 무엇에 대한
얘기인지 바로 알 수 있어야 한다. 대응 방향/제안 문장은 절대 쓰지 마라.

좋은 예: "영동 와인, 세계 교과서에 싣겠다" "이민정이 애정하는 와인 Better Half"
"홍콩 광동 식당 탐방기" "파리의 심판 와인, 경매서 고가 낙찰"
나쁜 예(너무 일반적이라 금지): "와인 추천" "맛집 정보" "와인 후기" "다양한 소식"

{chr(10).join(sections)}

반드시 아래 JSON 형식으로만 답하라(다른 텍스트 없이), 각 값은 문자열 배열(카테고리당 최대 2개):
{{"global": ["...", "..."], "consumer": ["...", "..."], "importer": ["...", "..."]}}
"""


def call_gemini(prompt: str, api_key: str, client=None, model: str = "gemini-flash-latest") -> dict[str, list[str]]:
    """무료 Gemini API 호출. responseMimeType=application/json으로 강제해서
    별도 재시도/파싱 방어 없이 바로 json.loads 가능하다.

    model 기본값이 "gemini-flash-latest"인 이유: 이 API 키의 무료 티어는
    "gemini-2.0-flash"처럼 버전을 못박은 모델은 quota=0으로 막혀 있고(2026-07-24
    확인, 429), "-latest" 별칭 모델만 무료 요청이 통과된다."""
    http = client or httpx
    response = http.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        params={"key": api_key},
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.3},
        },
        timeout=30.0,
    )
    response.raise_for_status()
    data = response.json()
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(text)


def get_week_end(week_start: str) -> str:
    start = datetime.strptime(week_start, "%Y-%m-%d").date()
    return (start + timedelta(days=6)).isoformat()


def _cache_path(week_start: str) -> Path:
    return SUMMARIES_DIR / f"{week_start}.json"


def load_cached(week_start: str) -> dict | None:
    return _load_json(_cache_path(week_start))


def save_cache(week_start: str, payload: dict) -> None:
    SUMMARIES_DIR.mkdir(parents=True, exist_ok=True)
    _cache_path(week_start).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def build_weekly_summary(week_start: str, api_key: str, client=None, force: bool = False) -> dict:
    """캐시 히트면 LLM 호출 없이 바로 반환, 미스면 Gemini 호출 후 파일 캐시에 쓴다.

    ponytail: git commit/push은 아직 안 함(로컬 파일 캐시만) — 로컬에서 먼저
    확인하고 배포 시 결정하기로 함(2026-07-24)."""
    entries_by_category = load_week_entries_by_category(week_start)
    fingerprint = compute_fingerprint(entries_by_category)

    if not force:
        cached = load_cached(week_start)
        if cached and cached.get("fingerprint") == fingerprint:
            return {**cached, "cached": True}

    buckets = bucket_entries(entries_by_category)
    counts = {b["key"]: len(buckets[b["key"]]) for b in BUCKETS}

    if sum(counts.values()) == 0:
        keywords = {b["key"]: [] for b in BUCKETS}
    else:
        keywords = call_gemini(build_prompt(buckets), api_key, client=client)

    payload = {
        "week_start": week_start,
        "week_end": get_week_end(week_start),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "fingerprint": fingerprint,
        "cached": False,
        "categories": [
            {
                "key": b["key"], "title": b["title"],
                # counts[key]==0인데 keywords만 있으면 LLM이 다른 버킷 내용을
                # 오분류해서 채운 것이다(실측 2026-07-24, "글로벌 동향" 입력이
                # 아예 없는데도 응답엔 채워져 있었음) — 원본 소스가 없으면
                # 무조건 빈 배열로 강제한다.
                "item_count": counts[b["key"]],
                "keywords": (keywords.get(b["key"]) or []) if counts[b["key"]] > 0 else [],
            }
            for b in BUCKETS
        ],
    }
    save_cache(week_start, payload)
    return payload
