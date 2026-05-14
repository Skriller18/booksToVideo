from __future__ import annotations

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


def build_audio_direction(spoken_line: str) -> str:
    return (
        f"Native audio: spoken line exactly: \"{spoken_line}\" "
        f"Voice profile: {VOICE_PROFILE}. "
        "Keep background ambience light and classroom-friendly, with no overpowering music or sound effects."
    )


def build_veo_prompt(clip: ClipBeat) -> str:
    reference_note = "based closely on the provided textbook illustration"
    if not clip.reference_illustrations:
        reference_note = "matching the chapter's simple textbook illustration style"

    return (
        f"Medium educational animated shot, {clip.visual_beat}. "
        f"{reference_note}. "
        f"Context: {clip.narration} "
        f"Style and ambience: {SERIES_STYLE}. "
        "Camera: slow gentle push-in or pan, stable composition, one focused visual action. "
        f"{clip.audio_direction}"
    )
