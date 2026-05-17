from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable


class PlaceholderError(RuntimeError):
    pass


def create_placeholder_clips(
    veo_manifest: dict[str, Any],
    media_root: Path,
    limit: int | None = None,
    duration_override: float | None = None,
    ffmpeg_path: str | None = None,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    ffmpeg = ffmpeg_path or shutil.which("ffmpeg")
    if not ffmpeg:
        raise PlaceholderError("ffmpeg is required to create placeholder clips but was not found on PATH")

    jobs = veo_manifest.get("jobs", [])
    if limit is not None:
        jobs = jobs[:limit]

    created = []
    total_jobs = len(jobs)
    for index, job in enumerate(jobs, start=1):
        output_path = _resolve_media_path(media_root, job["output_path"])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        duration = float(duration_override or job.get("duration_seconds") or 8)
        label = f"{job.get('episode_id', 'episode')} clip {job.get('episode_clip_index', '?')}"
        if progress:
            progress(str(output_path), index, total_jobs)
        command = _placeholder_command(ffmpeg, output_path, duration, label)
        _run(command)
        created.append(
            {
                "job_id": job.get("job_id"),
                "output_path": str(output_path),
                "duration_seconds": duration,
            }
        )

    return {
        "media_root": str(media_root),
        "created_clip_count": len(created),
        "created_clips": created,
    }


def _resolve_media_path(media_root: Path, path: str) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return media_root / candidate


def _placeholder_command(ffmpeg: str, output_path: Path, duration: float, label: str) -> list[str]:
    escaped_label = label.replace(":", "\\:").replace("'", "\\'")
    return [
        ffmpeg,
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c=0x1f2937:s=1280x720:d={duration}",
        "-vf",
        (
            "drawtext=fontcolor=white:fontsize=44:x=(w-text_w)/2:y=(h-text_h)/2:"
            f"text='{escaped_label}'"
        ),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-t",
        str(duration),
        str(output_path),
    ]


def _run(command: list[str]) -> None:
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise PlaceholderError(f"ffmpeg failed with exit code {result.returncode}: {stderr}")
ProgressCallback = Callable[[str, int | None, int | None], None]
