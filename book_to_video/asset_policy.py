from __future__ import annotations

import re
from pathlib import Path
from typing import Any


BLOCKED_ASSET_TERMS = {
    "barcode",
    "bar code",
    "qr",
    "qr code",
    "qrcode",
    "logo",
    "publisher",
    "watermark",
    "copyright",
    "icon",
    "audio icon",
    "speaker icon",
    "letter icon",
    "decorative",
    "ornament",
    "divider",
    "thumbnail",
}

GENERIC_ASSET_TERMS = {
    "asset",
    "image",
    "illustration",
    "figure",
    "fig",
    "page",
    "photo",
    "picture",
    "graphic",
    "diagram",
}


def asset_policy_metadata(raw: dict[str, Any]) -> dict[str, Any]:
    text = _asset_text(raw)
    blocked_terms = sorted(term for term in BLOCKED_ASSET_TERMS if term in text)
    if blocked_terms:
        return {
            "asset_type": "non_lesson_asset",
            "is_lesson_asset": False,
            "rejection_reason": f"blocked term: {blocked_terms[0]}",
        }
    if _looks_like_machine_code(text):
        return {
            "asset_type": "machine_readable_code",
            "is_lesson_asset": False,
            "rejection_reason": "machine readable code",
        }
    return {
        "asset_type": "candidate_lesson_illustration",
        "is_lesson_asset": True,
        "rejection_reason": "",
    }


def is_lesson_asset(raw: dict[str, Any]) -> bool:
    explicit = raw.get("is_lesson_asset")
    if explicit is not None:
        return bool(explicit)
    metadata = asset_policy_metadata(raw)
    return bool(metadata["is_lesson_asset"])


def lesson_relevance_score(raw: dict[str, Any], lesson_text: str) -> int:
    if not is_lesson_asset(raw):
        return -100

    lesson_words = _meaningful_words(lesson_text)
    asset_words = _meaningful_words(_asset_text(raw))
    if not asset_words:
        return 0
    return len(asset_words & lesson_words)


def _asset_text(raw: dict[str, Any]) -> str:
    parts = [
        str(raw.get("caption") or ""),
        str(raw.get("source_filename") or ""),
        Path(str(raw.get("path") or "")).name,
        str(raw.get("illustration_id") or ""),
    ]
    return " ".join(parts).replace("_", " ").replace("-", " ").lower()


def _meaningful_words(text: str) -> set[str]:
    words = set()
    for word in re.findall(r"[a-zA-Z]{3,}", text.lower()):
        if word in GENERIC_ASSET_TERMS:
            continue
        words.add(word)
    return words


def _looks_like_machine_code(text: str) -> bool:
    compact = re.sub(r"[^a-z0-9]", "", text.lower())
    if re.search(r"\b(?:isbn|issn)\b", text):
        return True
    return bool(re.fullmatch(r"[a-z]*\d{8,}[a-z]*", compact))
