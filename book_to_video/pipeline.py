from __future__ import annotations

from typing import Any

from .models import ClipBeat, Episode, StitchEpisode, to_dict
from .planner import build_episode_plan
from .prompts import build_veo_prompt
from .storyboard import build_clip_beats

DEFAULT_SOCIAL_SHORT_COUNT = 10


def build_planning_artifacts(
    chapter: dict[str, Any],
    target_episode_count: int | None,
    clips_per_episode: int,
    clip_duration_seconds: int,
    orchestrator: str = "local",
    orchestrator_model: str = "gemini-2.5-flash",
    content_mode: str = "educational",
    short_count: int = DEFAULT_SOCIAL_SHORT_COUNT,
) -> dict[str, Any]:
    episodes = build_episode_plan(
        chapter=chapter,
        target_episode_count=target_episode_count,
        clips_per_episode=clips_per_episode,
        clip_duration_seconds=clip_duration_seconds,
        content_mode=content_mode,
        short_count=short_count,
        orchestrator=orchestrator,
        orchestrator_model=orchestrator_model,
    )
    clips = build_clip_beats(
        chapter=chapter,
        episodes=episodes,
        clip_duration_seconds=clip_duration_seconds,
        orchestrator=orchestrator,
        orchestrator_model=orchestrator_model,
    )
    veo_manifest = build_veo_manifest(clips)
    stitch_manifest = build_stitch_manifest(episodes, clips, content_mode=content_mode)

    return {
        "episode_plan": {
            "chapter_id": chapter["chapter_id"],
            "chapter_title": chapter["title"],
            "content_mode": content_mode,
            "episode_count": len(episodes),
            "episodes": to_dict(episodes),
        },
        "storyboard": {
            "chapter_id": chapter["chapter_id"],
            "chapter_title": chapter["title"],
            "content_mode": content_mode,
            "clip_count": len(clips),
            "clips": to_dict(clips),
        },
        "veo_manifest": veo_manifest,
        "stitch_manifest": stitch_manifest,
    }


def build_veo_manifest(clips: list[ClipBeat]) -> dict[str, Any]:
    jobs = []
    for clip in clips:
        jobs.append(
            {
                "job_id": f"veo_{clip.global_clip_index:04d}",
                "chapter_id": clip.chapter_id,
                "episode_id": clip.episode_id,
                "global_clip_index": clip.global_clip_index,
                "episode_clip_index": clip.episode_clip_index,
                "duration_seconds": clip.duration_seconds,
                "prompt": build_veo_prompt(clip),
                "negative_prompt": clip.negative_prompt,
                "audio": {
                    "mode": "native",
                    "spoken_line": clip.narration,
                    "voice_profile": clip.voice_profile,
                    "audio_direction": clip.audio_direction,
                },
                "reference_images": [item.path for item in clip.reference_illustrations],
                "output_path": f"clips/clip_{clip.global_clip_index:04d}.mp4",
                "status": "pending",
            }
        )
    return {"clip_job_count": len(jobs), "jobs": jobs}


def build_stitch_manifest(
    episodes: list[Episode],
    clips: list[ClipBeat],
    content_mode: str = "educational",
) -> dict[str, Any]:
    stitch_episodes: list[StitchEpisode] = []
    for episode in episodes:
        episode_clips = [clip for clip in clips if clip.episode_id == episode.episode_id]
        clip_paths = [f"clips/clip_{clip.global_clip_index:04d}.mp4" for clip in episode_clips]
        stitch_episodes.append(
            StitchEpisode(
                episode_id=episode.episode_id,
                title=episode.title,
                output_video=f"episodes/{episode.episode_id}.mp4",
                clip_paths=clip_paths,
                duration_seconds=sum(clip.duration_seconds for clip in episode_clips),
            )
        )

    manifest = {
        "content_mode": content_mode,
        "episode_count": len(stitch_episodes),
        "episodes": to_dict(stitch_episodes),
    }
    if content_mode == "social":
        manifest["chapter_playlist"] = {}
    else:
        manifest["chapter_playlist"] = {
            "output_video": "chapter/full_chapter.mp4",
            "episode_paths": [episode.output_video for episode in stitch_episodes],
        }
    return manifest
