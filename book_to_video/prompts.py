from __future__ import annotations

import re

from .models import ClipBeat


SERIES_STYLE = (
    "continuous narrated scene for school students, clean colorful Indian schoolbook animation, "
    "warm classroom-friendly mood, simple backgrounds, clear educational framing, consistent silent characters"
)

SOCIAL_SERIES_STYLE = (
    "vertical social media short, bold clean visual metaphor, fast insight-led pacing, "
    "high-retention composition, simple cinematic motion, crisp Indian educational creator style, "
    "off-screen narrator voice-over"
)

NEGATIVE_PROMPT = (
    "no unreadable text, no random labels, no unrelated objects, no distorted faces, "
    "no scary visuals, no over-realistic style, no visual clutter"
)

VOICE_PROFILE = (
    "same warm Indian English off-screen narrator across all clips, friendly desi classroom tone, "
    "natural Indian accent, clear pronunciation for school students, expressive but not exaggerated"
)

SOCIAL_VOICE_PROFILE = (
    "clear Indian English social video narrator, curious and energetic but not shouty, "
    "fast enough for Shorts and Reels, precise pronunciation, insight-led creator tone"
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


def build_audio_direction(spoken_line: str, content_mode: str = "educational") -> str:
    spoken_line = sanitize_veo_text(spoken_line)
    voice_profile = SOCIAL_VOICE_PROFILE if content_mode == "social" else VOICE_PROFILE
    ambience = (
        "Keep background music light, modern, and low under the narration; no overpowering sound effects."
        if content_mode == "social"
        else "Keep background ambience light and classroom-friendly, with no overpowering music or sound effects."
    )
    return (
        f"Native audio: off-screen narrator voice-over says exactly: \"{spoken_line}\" "
        f"Voice profile: {voice_profile}. "
        "No lip sync, no character dialogue, and no visible speaker performing this line. "
        f"{ambience}"
    )


def build_veo_prompt(clip: ClipBeat) -> str:
    if clip.metadata.get("content_mode") == "social":
        return _build_social_veo_prompt(clip)

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
        f"Narrator voice-over context: {narration} "
        f"Style and ambience: {SERIES_STYLE}. "
        "Camera: slow gentle push-in or pan, stable composition, one focused visual action, "
        "natural continuity from the previous clip. Let the scene action continue naturally under the narration; "
        "characters may act silently but must not mouth the narration. "
        f"{audio_direction}"
    )


def _build_social_veo_prompt(clip: ClipBeat) -> str:
    reference_note = "use the provided book illustration only if it directly strengthens this viral insight"
    if not clip.reference_illustrations:
        reference_note = (
            "do not introduce textbook reference images; create an original vertical visual metaphor "
            "grounded in the narration"
        )

    visual_beat = sanitize_veo_text(clip.visual_beat)
    narration = sanitize_veo_text(clip.narration)
    audio_direction = sanitize_veo_text(clip.audio_direction)
    retention_role = sanitize_veo_text(str(clip.metadata.get("retention_role") or "short beat"))

    return (
        f"Vertical 9:16 social media short, {retention_role} beat, {_with_period(visual_beat)} "
        f"{_with_period(reference_note)} "
        f"Narrator voice-over context: {narration} "
        f"Style and ambience: {SOCIAL_SERIES_STYLE}. "
        "Camera: quick clean push-in, snappy match-cut energy, one strong visual idea, "
        "let the scene or metaphor play naturally under the narration, no readable on-screen text unless "
        "explicitly requested, no fake claims, no clutter, no visible speaker lip-syncing the narration. "
        f"{audio_direction}"
    )


def _with_period(text: str) -> str:
    text = text.strip()
    if not text:
        return ""
    if text[-1] in ".!?":
        return text
    return text + "."
