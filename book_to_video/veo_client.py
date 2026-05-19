from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .prompts import build_audio_direction, sanitize_veo_text


DEFAULT_VEO_MODEL = "veo-3.1-generate-preview"


class VeoGenerationError(RuntimeError):
    pass


@dataclass(frozen=True)
class VeoGenerationOptions:
    model: str = DEFAULT_VEO_MODEL
    aspect_ratio: str = "9:16"
    resolution: str = "720p"
    person_generation: str = "allow_all"
    poll_interval_seconds: int = 10
    max_polls: int = 60
    limit: int | None = None
    skip_existing: bool = True
    continuity_enabled: bool = True
    continuity_scope: str = "episode"
    ffmpeg_path: str | None = None
    failed_only: bool = False
    job_ids: tuple[str, ...] | None = None
    diagnostics_dir: Path | None = None
    episode_parallelism: int = 1


def generate_veo_clips_from_manifest(
    veo_manifest: dict[str, Any],
    media_root: Path,
    options: VeoGenerationOptions,
    persist_manifest: Callable[[dict[str, Any]], None] | None = None,
    client: Any | None = None,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Generate pending Veo clips and update the manifest in place.

    The optional client argument exists for tests. In production, this uses the
    Google Gen AI SDK and reads VERTEX_API_KEY/GEMINI_API_KEY/GOOGLE_API_KEY from the environment.
    """

    jobs = veo_manifest.get("jobs")
    if not isinstance(jobs, list):
        raise VeoGenerationError("veo_manifest.json must include a jobs array")

    media_root.mkdir(parents=True, exist_ok=True)
    if _can_parallelize_by_episode(options):
        return _generate_episode_groups_in_parallel(
            veo_manifest=veo_manifest,
            jobs=jobs,
            media_root=media_root,
            options=options,
            persist_manifest=persist_manifest,
            client=client,
            progress=progress,
        )

    generator = client or _build_google_genai_client()
    return _generate_job_sequence(
        veo_manifest=veo_manifest,
        indexed_jobs=list(enumerate(jobs, start=1)),
        media_root=media_root,
        options=options,
        generator=generator,
        persist_manifest=persist_manifest,
        progress=progress,
        total_jobs=len(jobs),
    )


def _generate_job_sequence(
    veo_manifest: dict[str, Any],
    indexed_jobs: list[tuple[int, Any]],
    media_root: Path,
    options: VeoGenerationOptions,
    generator: Any,
    persist_manifest: Callable[[dict[str, Any]], None] | None,
    progress: ProgressCallback | None,
    total_jobs: int,
) -> dict[str, Any]:

    result_jobs: list[dict[str, Any]] = []
    generated_count = 0
    skipped_count = 0
    failed_count = 0
    previous_last_frame: Path | None = None
    previous_scope_key: str | None = None

    for job_index, job in indexed_jobs:
        if not isinstance(job, dict):
            continue

        output_path = _resolve_output_path(media_root, job)
        job_label = job.get("job_id") or f"job {job_index}"
        scope_key = _continuity_scope_key(job, options)
        if scope_key != previous_scope_key:
            previous_last_frame = None
            previous_scope_key = scope_key

        start_frame_path = previous_last_frame if options.continuity_enabled else None
        _record_start_frame(job, start_frame_path)

        should_run, selection_reason = _should_run_selected_job(job, options)
        if not should_run:
            skipped_count += 1
            if progress:
                progress(f"skipped {job_label}: {selection_reason}", job_index, total_jobs)
            if output_path.exists() and str(job.get("status", "pending")) == "completed":
                previous_last_frame = _ensure_last_frame(job, output_path, media_root, options)
            result_jobs.append(_job_result(job, output_path, "skipped", selection_reason))
            if persist_manifest:
                persist_manifest(veo_manifest)
            continue

        should_skip, skip_reason = _should_skip_job(job, output_path, options)
        if should_skip:
            skipped_count += 1
            if progress:
                progress(f"skipped {job_label}: {skip_reason}", job_index, total_jobs)
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
            if progress:
                progress(f"skipped {job_label}: limit reached", job_index, total_jobs)
            result_jobs.append(_job_result(job, output_path, "skipped", "limit reached"))
            if persist_manifest:
                persist_manifest(veo_manifest)
            continue

        try:
            if progress:
                progress(f"submitting {job_label}", job_index, total_jobs)
            job["status"] = "running"
            job["veo_model"] = options.model
            job["started_at"] = _now_epoch()
            if persist_manifest:
                persist_manifest(veo_manifest)

            _sanitize_job_for_veo(job)
            operation = _submit_video_generation(generator, job, options, start_frame_path)
            job["operation_name"] = getattr(operation, "name", None) or job.get("operation_name")
            if progress:
                progress(f"polling {job_label}", job_index, total_jobs)
            operation = _poll_operation(generator, operation, options)
            if progress:
                progress(f"saving {job_label}", job_index, total_jobs)
            _save_generated_video(
                generator,
                operation,
                output_path,
                _diagnostics_path(media_root, job, options),
                job,
            )
            previous_last_frame = _ensure_last_frame(job, output_path, media_root, options)

            job["status"] = "completed"
            job["completed_at"] = _now_epoch()
            job["local_output_path"] = str(output_path)
            job.pop("error", None)
            generated_count += 1
            result_jobs.append(_job_result(job, output_path, "completed", "generated"))
            if progress:
                progress(f"completed {job_label}", job_index, total_jobs)
        except Exception as exc:
            job["status"] = "failed"
            job["error"] = str(exc)
            failed_count += 1
            result_jobs.append(_job_result(job, output_path, "failed", str(exc)))
            if progress:
                progress(f"failed {job_label}: {exc}", job_index, total_jobs)
        finally:
            if persist_manifest:
                persist_manifest(veo_manifest)

    return {
        "generated_clip_count": generated_count,
        "skipped_clip_count": skipped_count,
        "failed_clip_count": failed_count,
        "jobs": result_jobs,
    }


def _generate_episode_groups_in_parallel(
    veo_manifest: dict[str, Any],
    jobs: list[Any],
    media_root: Path,
    options: VeoGenerationOptions,
    persist_manifest: Callable[[dict[str, Any]], None] | None,
    client: Any | None,
    progress: ProgressCallback | None,
) -> dict[str, Any]:
    persist_lock = threading.Lock()
    progress_lock = threading.Lock()

    def locked_persist(payload: dict[str, Any]) -> None:
        if not persist_manifest:
            return
        with persist_lock:
            persist_manifest(payload)

    def locked_progress(message: str, current: int | None = None, total: int | None = None) -> None:
        if not progress:
            return
        with progress_lock:
            progress(message, current, total)

    groups = _episode_job_groups(jobs)
    max_workers = max(1, min(options.episode_parallelism, len(groups)))
    results: list[dict[str, Any]] = []

    def run_group(group: list[tuple[int, Any]]) -> dict[str, Any]:
        generator = client or _build_google_genai_client()
        return _generate_job_sequence(
            veo_manifest=veo_manifest,
            indexed_jobs=group,
            media_root=media_root,
            options=options,
            generator=generator,
            persist_manifest=locked_persist,
            progress=locked_progress,
            total_jobs=len(jobs),
        )

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(run_group, group) for group in groups]
        for future in as_completed(futures):
            results.append(future.result())

    result_jobs = [
        job_result
        for result in results
        for job_result in result.get("jobs", [])
    ]
    result_jobs.sort(key=lambda item: str(item.get("job_id") or ""))
    return {
        "generated_clip_count": sum(int(result.get("generated_clip_count", 0)) for result in results),
        "skipped_clip_count": sum(int(result.get("skipped_clip_count", 0)) for result in results),
        "failed_clip_count": sum(int(result.get("failed_clip_count", 0)) for result in results),
        "parallelism": max_workers,
        "parallelism_mode": "episode",
        "jobs": result_jobs,
    }


def _can_parallelize_by_episode(options: VeoGenerationOptions) -> bool:
    return (
        options.episode_parallelism > 1
        and options.continuity_scope == "episode"
        and options.limit is None
    )


def _episode_job_groups(jobs: list[Any]) -> list[list[tuple[int, Any]]]:
    groups_by_episode: dict[str, list[tuple[int, Any]]] = {}
    for index, job in enumerate(jobs, start=1):
        if not isinstance(job, dict):
            continue
        episode_id = str(job.get("episode_id") or "episode")
        groups_by_episode.setdefault(episode_id, []).append((index, job))
    return list(groups_by_episode.values())


def write_veo_operation_diagnostics(
    operation: Any,
    diagnostics_path: Path,
    job: dict[str, Any] | None = None,
) -> None:
    _write_operation_diagnostics(diagnostics_path, operation, job)


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
            "prompt": sanitize_veo_text(job["prompt"]),
            "config": config,
        }
        if start_frame_path:
            kwargs["image"] = _build_google_image(types, start_frame_path)
        return generator.models.generate_videos(**kwargs)
    except Exception as exc:
        raise VeoGenerationError(f"Veo submit failed for {job.get('job_id', 'unknown job')}: {exc}") from exc


def _sanitize_job_for_veo(job: dict[str, Any]) -> None:
    if "prompt" in job:
        job["prompt"] = sanitize_veo_text(str(job["prompt"]))
    audio = job.get("audio")
    if isinstance(audio, dict):
        if "spoken_line" in audio:
            audio["spoken_line"] = sanitize_veo_text(str(audio["spoken_line"]))
        if audio.get("spoken_line"):
            content_mode = "social" if "social" in str(audio.get("voice_profile", "")).lower() else "educational"
            audio["audio_direction"] = build_audio_direction(str(audio["spoken_line"]), content_mode=content_mode)
        elif "audio_direction" in audio:
            audio["audio_direction"] = sanitize_veo_text(str(audio["audio_direction"]))


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


def _save_generated_video(
    generator: Any,
    operation: Any,
    output_path: Path,
    diagnostics_path: Path | None = None,
    job: dict[str, Any] | None = None,
) -> None:
    if hasattr(generator, "save_generated_video"):
        generator.save_generated_video(operation, output_path)
        return

    response = getattr(operation, "response", None)
    generated_videos = getattr(response, "generated_videos", None) if response else None
    if not generated_videos:
        if diagnostics_path:
            _write_operation_diagnostics(diagnostics_path, operation, job)
            raise VeoGenerationError(
                "Veo operation completed without generated_videos; "
                f"wrote diagnostics to {diagnostics_path}"
            )
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


def _diagnostics_path(media_root: Path, job: dict[str, Any], options: VeoGenerationOptions) -> Path:
    diagnostics_dir = options.diagnostics_dir or media_root / "veo_diagnostics"
    job_id = str(job.get("job_id") or Path(str(job.get("output_path") or "clip")).stem)
    return diagnostics_dir / f"{job_id}_operation.json"


def _write_operation_diagnostics(
    diagnostics_path: Path,
    operation: Any,
    job: dict[str, Any] | None,
) -> None:
    diagnostics_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "written_at": _now_epoch(),
        "job": _diagnostic_job_payload(job or {}),
        "operation": _safe_serialize(operation),
        "operation_repr": repr(operation),
    }
    diagnostics_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _diagnostic_job_payload(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_id": job.get("job_id"),
        "status": job.get("status"),
        "operation_name": job.get("operation_name"),
        "output_path": job.get("output_path"),
        "veo_model": job.get("veo_model"),
        "duration_seconds": job.get("duration_seconds"),
        "continuity": job.get("continuity"),
        "error": job.get("error"),
    }


def _safe_serialize(value: Any, depth: int = 0) -> Any:
    if depth > 8:
        return repr(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, bytes):
        return f"<bytes {len(value)}>"
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {
            str(key): _safe_serialize(item, depth + 1)
            for key, item in value.items()
            if not _is_sensitive_key(str(key))
        }
    if isinstance(value, (list, tuple, set)):
        return [_safe_serialize(item, depth + 1) for item in value]
    if hasattr(value, "model_dump"):
        try:
            return _safe_serialize(value.model_dump(), depth + 1)
        except Exception:
            pass
    if hasattr(value, "to_dict"):
        try:
            return _safe_serialize(value.to_dict(), depth + 1)
        except Exception:
            pass
    if hasattr(value, "__dict__"):
        return _safe_serialize(vars(value), depth + 1)
    return repr(value)


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in ("api_key", "apikey", "token", "authorization", "secret"))


def _should_skip_job(job: dict[str, Any], output_path: Path, options: VeoGenerationOptions) -> tuple[bool, str]:
    status = str(job.get("status", "pending"))
    if status == "completed" and output_path.exists():
        return True, "already completed"
    if status == "completed" and not output_path.exists():
        return False, ""
    if options.skip_existing and output_path.exists():
        return True, "output file already exists"
    if status == "running":
        return False, ""
    if status not in {"pending", "failed"}:
        return True, f"status is {status}"
    return False, ""


def _should_run_selected_job(job: dict[str, Any], options: VeoGenerationOptions) -> tuple[bool, str]:
    job_id = str(job.get("job_id") or "")
    if options.job_ids is not None and job_id not in options.job_ids:
        return False, "not selected"
    if options.failed_only and str(job.get("status", "pending")) != "failed":
        return False, "status is not failed"
    return True, ""


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
ProgressCallback = Callable[[str, int | None, int | None], None]
