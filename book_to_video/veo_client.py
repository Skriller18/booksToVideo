from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


DEFAULT_VEO_MODEL = "veo-3.1-generate-preview"


class VeoGenerationError(RuntimeError):
    pass


@dataclass(frozen=True)
class VeoGenerationOptions:
    model: str = DEFAULT_VEO_MODEL
    aspect_ratio: str = "16:9"
    resolution: str = "720p"
    person_generation: str = "allow_all"
    poll_interval_seconds: int = 10
    max_polls: int = 60
    limit: int | None = None
    skip_existing: bool = True
    continuity_enabled: bool = True
    continuity_scope: str = "episode"
    ffmpeg_path: str | None = None


def generate_veo_clips_from_manifest(
    veo_manifest: dict[str, Any],
    media_root: Path,
    options: VeoGenerationOptions,
    persist_manifest: Callable[[dict[str, Any]], None] | None = None,
    client: Any | None = None,
) -> dict[str, Any]:
    """Generate pending Veo clips and update the manifest in place.

    The optional client argument exists for tests. In production, this uses the
    Google Gen AI SDK and reads VERTEX_API_KEY/GEMINI_API_KEY/GOOGLE_API_KEY from the environment.
    """

    jobs = veo_manifest.get("jobs")
    if not isinstance(jobs, list):
        raise VeoGenerationError("veo_manifest.json must include a jobs array")

    generator = client or _build_google_genai_client()
    media_root.mkdir(parents=True, exist_ok=True)

    result_jobs: list[dict[str, Any]] = []
    generated_count = 0
    skipped_count = 0
    failed_count = 0
    previous_last_frame: Path | None = None
    previous_scope_key: str | None = None

    for job in jobs:
        if not isinstance(job, dict):
            continue

        output_path = _resolve_output_path(media_root, job)
        scope_key = _continuity_scope_key(job, options)
        if scope_key != previous_scope_key:
            previous_last_frame = None
            previous_scope_key = scope_key

        start_frame_path = previous_last_frame if options.continuity_enabled else None
        _record_start_frame(job, start_frame_path)

        should_skip, skip_reason = _should_skip_job(job, output_path, options)
        if should_skip:
            skipped_count += 1
            if output_path.exists():
                job["status"] = "completed"
                job["local_output_path"] = str(output_path)
                previous_last_frame = _ensure_last_frame(job, output_path, media_root, options)
            result_jobs.append(_job_result(job, output_path, "skipped", skip_reason))
            if persist_manifest:
                persist_manifest(veo_manifest)
            continue

        if options.limit is not None and generated_count >= options.limit:
            skipped_count += 1
            result_jobs.append(_job_result(job, output_path, "skipped", "limit reached"))
            if persist_manifest:
                persist_manifest(veo_manifest)
            continue

        try:
            job["status"] = "running"
            job["veo_model"] = options.model
            job["started_at"] = _now_epoch()
            if persist_manifest:
                persist_manifest(veo_manifest)

            operation = _submit_video_generation(generator, job, options, start_frame_path)
            job["operation_name"] = getattr(operation, "name", None) or job.get("operation_name")
            operation = _poll_operation(generator, operation, options)
            _save_generated_video(generator, operation, output_path)
            previous_last_frame = _ensure_last_frame(job, output_path, media_root, options)

            job["status"] = "completed"
            job["completed_at"] = _now_epoch()
            job["local_output_path"] = str(output_path)
            job.pop("error", None)
            generated_count += 1
            result_jobs.append(_job_result(job, output_path, "completed", "generated"))
        except Exception as exc:
            job["status"] = "failed"
            job["error"] = str(exc)
            failed_count += 1
            result_jobs.append(_job_result(job, output_path, "failed", str(exc)))
        finally:
            if persist_manifest:
                persist_manifest(veo_manifest)

    return {
        "generated_clip_count": generated_count,
        "skipped_clip_count": skipped_count,
        "failed_clip_count": failed_count,
        "jobs": result_jobs,
    }


def _build_google_genai_client() -> Any:
    api_key = (
        os.environ.get("VERTEX_API_KEY")
        or os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
    )
    if not api_key:
        raise VeoGenerationError(
            "VERTEX_API_KEY, GEMINI_API_KEY, or GOOGLE_API_KEY is required for Veo generation"
        )

    try:
        from google import genai
    except ImportError as exc:
        raise VeoGenerationError(
            "google-genai is required for Veo generation. Install it with: "
            "python3 -m pip install google-genai"
        ) from exc

    return genai.Client(api_key=api_key)


def _submit_video_generation(
    generator: Any,
    job: dict[str, Any],
    options: VeoGenerationOptions,
    start_frame_path: Path | None,
) -> Any:
    if hasattr(generator, "submit_video_generation"):
        return generator.submit_video_generation(job, options, start_frame_path)

    try:
        from google.genai import types
    except ImportError as exc:
        raise VeoGenerationError("google-genai is required for Veo generation") from exc

    config_kwargs: dict[str, Any] = {
        "number_of_videos": 1,
        "aspect_ratio": options.aspect_ratio,
        "resolution": options.resolution,
        "person_generation": options.person_generation,
    }
    duration_seconds = job.get("duration_seconds")
    if duration_seconds is not None:
        config_kwargs["duration_seconds"] = int(duration_seconds)

    config = _build_generate_videos_config(types, config_kwargs)
    try:
        kwargs: dict[str, Any] = {
            "model": options.model,
            "prompt": job["prompt"],
            "config": config,
        }
        if start_frame_path:
            kwargs["image"] = _build_google_image(types, start_frame_path)
        return generator.models.generate_videos(**kwargs)
    except Exception as exc:
        raise VeoGenerationError(f"Veo submit failed for {job.get('job_id', 'unknown job')}: {exc}") from exc


def _build_google_image(types: Any, image_path: Path) -> Any:
    try:
        return types.Image.from_file(location=str(image_path))
    except TypeError:
        return types.Image.from_file(str(image_path))


def _build_generate_videos_config(types: Any, config_kwargs: dict[str, Any]) -> Any:
    try:
        return types.GenerateVideosConfig(**config_kwargs)
    except TypeError:
        # Keep compatibility with older google-genai releases that may not yet
        # expose every newer Veo parameter.
        fallback_keys = ("number_of_videos", "aspect_ratio", "resolution")
        fallback = {key: config_kwargs[key] for key in fallback_keys if key in config_kwargs}
        return types.GenerateVideosConfig(**fallback)


def _poll_operation(generator: Any, operation: Any, options: VeoGenerationOptions) -> Any:
    if hasattr(generator, "poll_video_generation"):
        return generator.poll_video_generation(operation, options)

    for _ in range(options.max_polls):
        if getattr(operation, "done", False):
            error = getattr(operation, "error", None)
            if error:
                raise VeoGenerationError(f"Veo operation failed: {error}")
            return operation
        time.sleep(options.poll_interval_seconds)
        operation = generator.operations.get(operation)
    operation_name = getattr(operation, "name", "unknown operation")
    raise VeoGenerationError(f"Veo operation did not complete after {options.max_polls} polls: {operation_name}")


def _save_generated_video(generator: Any, operation: Any, output_path: Path) -> None:
    if hasattr(generator, "save_generated_video"):
        generator.save_generated_video(operation, output_path)
        return

    response = getattr(operation, "response", None)
    generated_videos = getattr(response, "generated_videos", None) if response else None
    if not generated_videos:
        raise VeoGenerationError("Veo operation completed without generated_videos")

    video = generated_videos[0].video
    output_path.parent.mkdir(parents=True, exist_ok=True)
    generator.files.download(file=video)

    if hasattr(video, "save"):
        video.save(str(output_path))
        return
    video_bytes = getattr(video, "video_bytes", None) or getattr(video, "videoBytes", None)
    if video_bytes:
        output_path.write_bytes(video_bytes)
        return
    raise VeoGenerationError("Could not save generated video from Google Gen AI SDK response")


def _should_skip_job(job: dict[str, Any], output_path: Path, options: VeoGenerationOptions) -> tuple[bool, str]:
    status = str(job.get("status", "pending"))
    if status == "completed" and output_path.exists():
        return True, "already completed"
    if options.skip_existing and output_path.exists():
        return True, "output file already exists"
    if status == "running":
        return False, ""
    if status not in {"pending", "failed"}:
        return True, f"status is {status}"
    return False, ""


def _resolve_output_path(media_root: Path, job: dict[str, Any]) -> Path:
    output_path = Path(str(job.get("output_path") or f"clips/{job.get('job_id', 'clip')}.mp4"))
    if output_path.is_absolute():
        return output_path
    return media_root / output_path


def _continuity_scope_key(job: dict[str, Any], options: VeoGenerationOptions) -> str:
    if options.continuity_scope == "chapter":
        return "chapter"
    return str(job.get("episode_id") or "episode")


def _record_start_frame(job: dict[str, Any], start_frame_path: Path | None) -> None:
    continuity = dict(job.get("continuity") or {})
    if start_frame_path:
        continuity["start_frame_path"] = str(start_frame_path)
        continuity["mode"] = "previous_clip_last_frame"
    else:
        continuity.pop("start_frame_path", None)
        continuity["mode"] = "none"
    job["continuity"] = continuity


def _ensure_last_frame(
    job: dict[str, Any],
    output_path: Path,
    media_root: Path,
    options: VeoGenerationOptions,
) -> Path | None:
    if not options.continuity_enabled:
        return None
    continuity = dict(job.get("continuity") or {})
    last_frame_path = Path(
        continuity.get("last_frame_path")
        or _default_last_frame_path(media_root, job)
    )
    if not last_frame_path.is_absolute():
        last_frame_path = media_root / last_frame_path
    if not last_frame_path.exists():
        _extract_last_frame(output_path, last_frame_path, options)
    continuity["last_frame_path"] = str(last_frame_path)
    job["continuity"] = continuity
    return last_frame_path


def _default_last_frame_path(media_root: Path, job: dict[str, Any]) -> Path:
    job_id = str(job.get("job_id") or Path(str(job.get("output_path") or "clip")).stem)
    return media_root / "continuity" / f"{job_id}_last_frame.png"


def _extract_last_frame(video_path: Path, frame_path: Path, options: VeoGenerationOptions) -> None:
    ffmpeg = options.ffmpeg_path or shutil.which("ffmpeg")
    if not ffmpeg:
        raise VeoGenerationError("ffmpeg is required to extract continuity frames but was not found on PATH")
    frame_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg,
        "-y",
        "-sseof",
        "-0.08",
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        str(frame_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise VeoGenerationError(f"ffmpeg failed to extract continuity frame: {stderr}")


def _job_result(job: dict[str, Any], output_path: Path, action: str, detail: str) -> dict[str, Any]:
    return {
        "job_id": job.get("job_id"),
        "status": job.get("status"),
        "action": action,
        "detail": detail,
        "output_path": str(output_path),
        "continuity": job.get("continuity"),
    }


def _now_epoch() -> int:
    return int(time.time())
