from __future__ import annotations

import re

from .models import ClipBeat


SERIES_STYLE = (
    "textbook illustration brought to life, clean colorful Indian schoolbook animation, "
    "warm classroom-friendly mood, simple backgrounds, clear educational framing"
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
        r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\s+is\s+one\s+of\b",
        "The author is one of",
        sanitized,
    )
    sanitized = re.sub(
        r"\bby\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\b",
        "by the author",
        sanitized,
        flags=re.IGNORECASE,
    )
    # Known textbook author names should not be sent to video generation models;
    # some providers reject real-person names even when the content is educational.
    sanitized = re.sub(r"\bRuskin\s+Bond\b", "the author", sanitized, flags=re.IGNORECASE)
    return sanitized


def build_audio_direction(spoken_line: str) -> str:
    spoken_line = sanitize_veo_text(spoken_line)
    return (
        f"Native audio: spoken line exactly: \"{spoken_line}\" "
        f"Voice profile: {VOICE_PROFILE}. "
        "Keep background ambience light and classroom-friendly, with no overpowering music or sound effects."
    )


def build_veo_prompt(clip: ClipBeat) -> str:
    reference_note = "based closely on the provided textbook illustration"
    if not clip.reference_illustrations:
        reference_note = "matching the chapter's simple textbook illustration style"

    visual_beat = sanitize_veo_text(clip.visual_beat)
    narration = sanitize_veo_text(clip.narration)
    audio_direction = sanitize_veo_text(clip.audio_direction)

    return (
        f"Medium educational animated shot, {visual_beat}. "
        f"{reference_note}. "
        f"Context: {narration} "
        f"Style and ambience: {SERIES_STYLE}. "
        "Camera: slow gentle push-in or pan, stable composition, one focused visual action. "
        f"{audio_direction}"
    )
