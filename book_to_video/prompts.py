from __future__ import annotations

import re

from .models import ClipBeat


SERIES_STYLE = (
    "continuous microdrama for school students, clean colorful Indian schoolbook animation, "
    "warm classroom-friendly mood, simple backgrounds, clear educational framing, consistent characters"
)

NEGATIVE_PROMPT = (
    "no unreadable text, no random labels, no unrelated objects, no distorted faces, "
    "no scary visuals, no over-realistic style, no visual clutter"
)

VOICE_PROFILE = (
    "same warm Indian English teacher voice across all clips, friendly desi classroom tone, "
    "natural Indian accent, clear pronunciation for school students, expressive but not exaggerated"
)


def sanitize_veo_text(text: str) -> str:
    sanitized = " ".join(text.split())
    sanitized = re.sub(
        r"\bRuskin\s+Bond\s+is\s+one\s+of\b",
        "The author is one of",
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(
        r"\bRuskin\s+Bond\b",
        "the author",
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(
        r"\bSpeaker icon indicating audio content\.\s*",
        "",
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(
        r"\bLetter [A-Z] icon indicating audio content\.\s*",
        "",
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(
        r"\b([A-Z][a-z]+\s+[A-Z][a-z]+)\s+is\s+one\s+of\b",
        "The author is one of",
        sanitized,
    )
    sanitized = re.sub(
        r"\bby\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\b",
        "by the author",
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = sanitized.replace(
        "The Boy Who Broke the The author is one of",
        "The Boy Who Broke the Bank. The author is one of",
    )
    return sanitized


def build_audio_direction(spoken_line: str) -> str:
    spoken_line = sanitize_veo_text(spoken_line)
    return (
        f"Native audio: spoken line exactly: \"{spoken_line}\" "
        f"Voice profile: {VOICE_PROFILE}. "
        "Keep background ambience light and classroom-friendly, with no overpowering music or sound effects."
    )


def build_veo_prompt(clip: ClipBeat) -> str:
    reference_note = "use the provided textbook illustration only as the meaningful visual reference for this beat"
    if not clip.reference_illustrations:
        reference_note = (
            "do not introduce textbook reference images for this beat; keep continuity from the episode "
            "and use simple original classroom visuals"
        )

    visual_beat = sanitize_veo_text(clip.visual_beat)
    narration = sanitize_veo_text(clip.narration)
    audio_direction = sanitize_veo_text(clip.audio_direction)

    return (
        f"Medium educational animated shot, {_with_period(visual_beat)} "
        f"{_with_period(reference_note)} "
        f"Context: {narration} "
        f"Style and ambience: {SERIES_STYLE}. "
        "Camera: slow gentle push-in or pan, stable composition, one focused visual action, "
        "natural continuity from the previous clip. "
        f"{audio_direction}"
    )


def _with_period(text: str) -> str:
    text = text.strip()
    if not text:
        return ""
    if text[-1] in ".!?":
        return text
    return text + "."
