from __future__ import annotations

import re
from collections import Counter


ASCII_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+", re.UNICODE)
CHINESE_CHAR_RE = re.compile(r"[\u4e00-\u9fff]", re.UNICODE)


def tokenize(text: str) -> list[str]:
    ascii_tokens = [token.lower() for token in ASCII_TOKEN_RE.findall(text)]
    chinese_chars = CHINESE_CHAR_RE.findall(text)
    chinese_bigrams = [
        "".join(chinese_chars[index : index + 2])
        for index in range(max(0, len(chinese_chars) - 1))
    ]
    return ascii_tokens + chinese_chars + chinese_bigrams


def meaningful_tokens(text: str) -> list[str]:
    ascii_tokens = [token.lower() for token in ASCII_TOKEN_RE.findall(text)]
    chinese_chars = CHINESE_CHAR_RE.findall(text)
    chinese_bigrams = [
        "".join(chinese_chars[index : index + 2])
        for index in range(max(0, len(chinese_chars) - 1))
    ]
    return ascii_tokens + chinese_bigrams


def token_set(text: str) -> set[str]:
    return set(tokenize(text))


def token_overlap(a: str, b: str) -> float:
    left = token_set(a)
    right = token_set(b)
    if not left or not right:
        return 0.0
    return len(left & right) / max(1, len(left | right))


def keyword_score(query: str, text: str) -> float:
    q = Counter(meaningful_tokens(query))
    t = Counter(meaningful_tokens(text))
    if not q or not t:
        return 0.0
    overlap = sum(min(q[token], t[token]) for token in q)
    return overlap / max(1, sum(q.values()))


def compact_text(text: str, max_chars: int = 280) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max_chars - 3].rstrip() + "..."
