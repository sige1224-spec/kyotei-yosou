"""スクレイパー各モジュール共通のテキスト正規化ヘルパー。"""
from __future__ import annotations

import re
import unicodedata


def zenkaku_to_int(text: str) -> int:
    normalized = unicodedata.normalize("NFKC", text).strip()
    return int(normalized) if normalized.lstrip("-").isdigit() else 0


def safe_float(text: str) -> float:
    normalized = unicodedata.normalize("NFKC", text).strip()
    match = re.search(r"-?\d+(\.\d+)?", normalized)
    return float(match.group()) if match else 0.0


def safe_int(text: str) -> int:
    normalized = unicodedata.normalize("NFKC", text).strip()
    match = re.search(r"-?\d+", normalized)
    return int(match.group()) if match else 0


def normalize_name(text: str) -> str:
    return re.sub(r"[\s　]+", " ", text).strip()
