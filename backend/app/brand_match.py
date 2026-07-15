from __future__ import annotations
import re

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_ASCII_WORD_CHAR_RE = re.compile(r"[A-Za-z0-9]")


def make_excerpt(html_or_text: str, max_length: int = 200) -> str:
    text = _TAG_RE.sub(" ", html_or_text)
    text = _WS_RE.sub(" ", text).strip()
    if len(text) <= max_length:
        return text
    truncated = text[:max_length]
    last_space = truncated.rfind(" ")
    return (truncated[:last_space] if last_space > 0 else truncated).strip()


def _is_ascii_word_char(ch: str | None) -> bool:
    return ch is not None and bool(_ASCII_WORD_CHAR_RE.match(ch))


# 순수 부분 문자열 매칭은 짧은 브랜드명이 더 큰 영단어 안에 우연히 포함될 때
# 오탐을 낸다(2026-07-10 매거진 적재 중 실제로 발견 — "Iter"가 "Writer" 안에서
# 매칭돼 잘못 태깅됨). 매칭 지점 앞뒤 글자가 ASCII 영숫자가 아닐 때만
# (한글/공백/문장부호/문자열 경계는 전부 허용) 유효한 매칭으로 인정한다.
# scripts/lib/article-shared.ts의 matchBrands를 그대로 이식.
def match_brands(text: str, known_brands: list[str]) -> list[str]:
    lower_text = text.lower()
    matched: list[str] = []
    for brand in known_brands:
        needle = brand.lower()
        if not needle:
            continue
        idx = lower_text.find(needle)
        found = False
        while idx != -1:
            before = lower_text[idx - 1] if idx > 0 else None
            after_pos = idx + len(needle)
            after = lower_text[after_pos] if after_pos < len(lower_text) else None
            if not _is_ascii_word_char(before) and not _is_ascii_word_char(after):
                found = True
                break
            idx = lower_text.find(needle, idx + 1)
        if found:
            matched.append(brand)

    seen: set[str] = set()
    result: list[str] = []
    for b in matched:
        if b not in seen:
            seen.add(b)
            result.append(b)
    return result
