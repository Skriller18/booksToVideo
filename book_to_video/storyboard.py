from __future__ import annotations

from typing import Any

from .models import ClipBeat, Episode
from .orchestrator import build_orchestrated_episode_clips
from .prompts import NEGATIVE_PROMPT, VOICE_PROFILE, build_audio_direction, build_veo_prompt


def build_clip_beats(
    chapter: dict[str, Any],
    episodes: list[Episode],
    clip_duration_seconds: int,
    orchestrator: str = "local",
    orchestrator_model: str = "gemini-2.5-flash",
) -> list[ClipBeat]:
    clips: list[ClipBeat] = []
    global_index = 1

    for episode in episodes:
        orchestrated_clips = build_orchestrated_episode_clips(
            chapter=chapter,
            episode=episode,
            clip_count=episode.clip_count,
            orchestrator=orchestrator,
            orchestrator_model=orchestrator_model,
        )
        for episode_clip_index, orchestrated_clip in enumerate(orchestrated_clips, start=1):
            clip = ClipBeat(
                chapter_id=chapter["chapter_id"],
                episode_id=episode.episode_id,
                global_clip_index=global_index,
                episode_clip_index=episode_clip_index,
                duration_seconds=clip_duration_seconds,
                source_pages=episode.source_pages,
                reference_illustrations=orchestrated_clip.reference_illustrations,
                narration=orchestrated_clip.narration,
                voice_profile=VOICE_PROFILE,
                audio_direction=build_audio_direction(orchestrated_clip.narration),
                visual_beat=orchestrated_clip.visual_beat,
                veo_prompt="",
                negative_prompt=NEGATIVE_PROMPT,
                transition=orchestrated_clip.transition,
                metadata={
                    **orchestrated_clip.metadata,
                    "arc_key": orchestrated_clip.arc_key,
                },
            )
            clips.append(
                ClipBeat(
                    **{
                        **clip.__dict__,
                        "veo_prompt": build_veo_prompt(clip),
                    }
                )
            )
            global_index += 1

    return clips
