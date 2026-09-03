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
