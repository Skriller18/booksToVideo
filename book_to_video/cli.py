from __future__ import annotations

import argparse
import os
from dataclasses import replace
from pathlib import Path
from typing import Any

from .datalab_client import DatalabConvertClient, DatalabConvertOptions
from .datalab_extractor import normalize_datalab_convert_result
from .io_utils import read_json, write_json
from .pipeline import build_planning_artifacts
from .placeholders import create_placeholder_clips
from .progress import ProgressTracker
from .stitcher import stitch_from_manifest
from .veo_client import DEFAULT_VEO_MODEL, VeoGenerationOptions, generate_veo_clips_from_manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="book-to-video",
        description="Plan textbook chapter videos as 2-minute episodes made from 8-second clips.",
    )
    parser.add_argument(
        "--env-file",
        default=None,
        help="Path to a .env file. Defaults to .env in the current working directory if present.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser(
        "run",
        help="Run extraction, planning, Veo generation, and stitching as one pipeline.",
    )
    run.add_argument("--pdf", help="Path to chapter PDF. Required unless --raw-json is provided.")
    run.add_argument("--raw-json", help="Use a saved Datalab result instead of calling the API.")
    run.add_argument("--output-dir", required=True, help="Directory where all pipeline artifacts are written.")
    run.add_argument("--chapter-id", help="Optional stable chapter id.")
    run.add_argument("--chapter-title", help="Optional chapter title override.")
    run.add_argument("--mode", default="accurate", choices=("fast", "balanced", "accurate"))
    run.add_argument("--max-pages", type=int, default=None)
    run.add_argument("--page-range", default=None, help='Datalab page range, for example "0-5,10".')
    run.add_argument("--poll-interval", type=int, default=2)
    run.add_argument("--max-polls", type=int, default=300)
    run.add_argument("--skip-cache", action="store_true")
    run.add_argument("--episode-count", type=int, default=None)
    run.add_argument("--clips-per-episode", type=int, default=15)
    run.add_argument("--clip-duration", type=int, default=8, choices=(4, 6, 8))
    run.add_argument("--veo-model", default=DEFAULT_VEO_MODEL, help=f"Veo model id. Default: {DEFAULT_VEO_MODEL}.")
    run.add_argument("--veo-limit", type=int, default=None, help="Generate only the first N runnable clips.")
    run.add_argument(
        "--veo-retry-missing-attempts",
        type=int,
        default=1,
        help="Retry missing or failed Veo clips this many times before stitching. Default: 1.",
    )
    run.add_argument("--veo-poll-interval", type=int, default=10)
    run.add_argument("--veo-max-polls", type=int, default=60)
    run.add_argument("--aspect-ratio", default="16:9", choices=("16:9", "9:16"))
    run.add_argument("--resolution", default="720p", choices=("720p", "1080p", "4k"))
    run.add_argument("--person-generation", default="allow_all")
    run.add_argument("--overwrite-existing", action="store_true")
    run.add_argument("--no-continuity", action="store_true", help="Do not feed prior clip frames into Veo.")
    run.add_argument("--continuity-scope", default="episode", choices=("episode", "chapter"))
    run.add_argument("--mock-clips", action="store_true", help="Create placeholder clips instead of calling Veo.")
    run.add_argument("--mock-duration", type=float, default=None, help="Override placeholder duration.")
    run.add_argument("--episodes-only", action="store_true", help="Skip the full chapter playlist video.")
    run.add_argument("--copy-codecs", action="store_true")

    plan = subparsers.add_parser("plan", help="Build episode, storyboard, Veo, and stitch manifests.")
    plan.add_argument("--chapter-json", required=True, help="Path to chapter_extraction.json.")
    plan.add_argument("--output-dir", required=True, help="Directory where planning artifacts are written.")
    plan.add_argument(
        "--episode-count",
        type=int,
        default=None,
        help="Optional target number of topic episodes. Defaults to one episode per detected topic.",
    )
    plan.add_argument(
        "--clips-per-episode",
        type=int,
        default=15,
        help="Number of 8-second clips per 2-minute episode. Default: 15.",
    )
    plan.add_argument(
        "--clip-duration",
        type=int,
        default=8,
        choices=(4, 6, 8),
        help="Clip duration in seconds. Default: 8.",
    )

    extract = subparsers.add_parser(
        "extract-datalab",
        help="Extract chapter text and illustrations using Datalab Convert API.",
    )
    extract.add_argument("--pdf", help="Path to chapter PDF. Required unless --raw-json is provided.")
    extract.add_argument("--raw-json", help="Normalize a saved Datalab result instead of calling the API.")
    extract.add_argument("--output-dir", required=True, help="Directory where extraction artifacts are written.")
    extract.add_argument("--chapter-id", help="Optional stable chapter id.")
    extract.add_argument("--chapter-title", help="Optional chapter title override.")
    extract.add_argument("--mode", default="accurate", choices=("fast", "balanced", "accurate"))
    extract.add_argument("--max-pages", type=int, default=None)
    extract.add_argument("--page-range", default=None, help='Datalab page range, for example "0-5,10".')
    extract.add_argument("--poll-interval", type=int, default=2)
    extract.add_argument("--max-polls", type=int, default=300)
    extract.add_argument("--skip-cache", action="store_true")

    stitch = subparsers.add_parser(
        "stitch",
        help="Stitch generated 8-second clips into episode videos and an optional chapter video.",
    )
    stitch.add_argument("--stitch-manifest", required=True, help="Path to stitch_manifest.json.")
    stitch.add_argument(
        "--media-root",
        help="Root directory for relative clip paths. Defaults to the manifest directory.",
    )
    stitch.add_argument(
        "--output-dir",
        help="Root directory for relative output paths. Defaults to the manifest directory.",
    )
    stitch.add_argument("--dry-run", action="store_true", help="Report planned stitching without running ffmpeg.")
    stitch.add_argument(
        "--episodes-only",
        action="store_true",
        help="Only stitch episode videos; skip the full chapter playlist video.",
    )
    stitch.add_argument(
        "--copy-codecs",
        action="store_true",
        help="Use ffmpeg stream copy instead of re-encoding. Faster but less tolerant.",
    )

    placeholders = subparsers.add_parser(
        "mock-clips",
        help="Create local placeholder MP4 clips from veo_manifest.json for end-to-end stitching tests.",
    )
    placeholders.add_argument("--veo-manifest", required=True, help="Path to veo_manifest.json.")
    placeholders.add_argument(
        "--media-root",
        help="Root directory for relative clip output paths. Defaults to the manifest directory.",
    )
    placeholders.add_argument("--limit", type=int, default=None, help="Only create the first N clips.")
    placeholders.add_argument(
        "--duration",
        type=float,
        default=None,
        help="Override clip duration for faster local tests.",
    )

    veo = subparsers.add_parser(
        "generate-veo",
        help="Generate real Veo clips from veo_manifest.json using the Gemini API.",
    )
    veo.add_argument("--veo-manifest", required=True, help="Path to veo_manifest.json.")
    veo.add_argument(
        "--media-root",
        help="Root directory for relative clip output paths. Defaults to the manifest directory.",
    )
    veo.add_argument("--model", default=DEFAULT_VEO_MODEL, help=f"Veo model id. Default: {DEFAULT_VEO_MODEL}.")
    veo.add_argument("--limit", type=int, default=None, help="Generate only the first N runnable clips.")
    veo.add_argument(
        "--failed-only",
        action="store_true",
        help="Only rerun jobs currently marked failed in veo_manifest.json.",
    )
    veo.add_argument(
        "--job-id",
        action="append",
        default=None,
        help="Only run a specific Veo job id, for example veo_0006. Can be passed multiple times.",
    )
    veo.add_argument("--poll-interval", type=int, default=10, help="Seconds between Veo operation polls.")
    veo.add_argument("--max-polls", type=int, default=60, help="Maximum polls per clip before failing it.")
    veo.add_argument("--aspect-ratio", default="16:9", choices=("16:9", "9:16"))
    veo.add_argument("--resolution", default="720p", choices=("720p", "1080p", "4k"))
    veo.add_argument("--person-generation", default="allow_all")
    veo.add_argument(
        "--overwrite-existing",
        action="store_true",
        help="Regenerate clips even when the output MP4 already exists.",
    )
    veo.add_argument("--no-continuity", action="store_true", help="Do not feed prior clip frames into Veo.")
    veo.add_argument("--continuity-scope", default="episode", choices=("episode", "chapter"))
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    load_env_file(Path(args.env_file) if args.env_file else Path.cwd() / ".env")

    if args.command == "run":
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        pipeline_progress = ProgressTracker(total=5, description="Pipeline")
        pipeline_progress.write(f"Output directory: {output_dir}")

        if args.raw_json:
            pipeline_progress.write(f"Reading saved Datalab response: {args.raw_json}")
            datalab_result = read_json(Path(args.raw_json))
            source_pdf = args.pdf or datalab_result.get("source_pdf") or "unknown.pdf"
        else:
            if not args.pdf:
                parser.error("--pdf is required unless --raw-json is provided")
            api_key = os.environ.get("DATALAB_API_KEY", "")
            client = DatalabConvertClient(api_key=api_key)
            datalab_options = DatalabConvertOptions(
                output_format="json",
                mode=args.mode,
                paginate=True,
                disable_image_extraction=False,
                disable_image_captions=False,
                max_pages=args.max_pages,
                page_range=args.page_range,
                skip_cache=args.skip_cache,
            )
            datalab_progress = pipeline_progress.child(args.max_polls, "Datalab polling")
            datalab_result = client.convert_pdf(
                Path(args.pdf),
                options=datalab_options,
                poll_interval_seconds=args.poll_interval,
                max_polls=args.max_polls,
                progress=_progress_callback(datalab_progress),
            )
            datalab_progress.close()
            source_pdf = args.pdf
            write_json(output_dir / "raw_datalab_convert.json", datalab_result)
            pipeline_progress.write(f"Wrote raw Datalab response: {output_dir / 'raw_datalab_convert.json'}")
        pipeline_progress.update("Datalab extraction")

        pipeline_progress.write("Normalizing Datalab response into chapter extraction")
        chapter = normalize_datalab_convert_result(
            datalab_result=datalab_result,
            source_pdf=source_pdf,
            output_dir=output_dir,
            chapter_id=args.chapter_id,
            chapter_title=args.chapter_title,
        )
        write_json(output_dir / "chapter_extraction.json", chapter)
        pipeline_progress.write(
            "Wrote chapter extraction: "
            f"{len(chapter['pages'])} pages, {len(chapter['topics'])} topics"
        )
        pipeline_progress.update("Chapter normalization")

        pipeline_progress.write("Building episode plan, storyboard, Veo manifest, and stitch manifest")
        artifacts = build_planning_artifacts(
            chapter,
            target_episode_count=args.episode_count,
            clips_per_episode=args.clips_per_episode,
            clip_duration_seconds=args.clip_duration,
        )
        write_json(output_dir / "episode_plan.json", artifacts["episode_plan"])
        write_json(output_dir / "storyboard.json", artifacts["storyboard"])
        write_json(output_dir / "veo_manifest.json", artifacts["veo_manifest"])
        write_json(output_dir / "stitch_manifest.json", artifacts["stitch_manifest"])
        pipeline_progress.write(
            "Wrote planning artifacts: "
            f"{artifacts['episode_plan']['episode_count']} episodes, "
            f"{artifacts['storyboard']['clip_count']} clips"
        )
        pipeline_progress.update("Planning")

        if args.mock_clips:
            pipeline_progress.write("Creating placeholder clips")
            clip_jobs = artifacts["veo_manifest"].get("jobs", [])
            clip_progress = pipeline_progress.child(len(clip_jobs), "Mock clips")
            clip_result = create_placeholder_clips(
                veo_manifest=artifacts["veo_manifest"],
                media_root=output_dir,
                duration_override=args.mock_duration,
                progress=_progress_callback(clip_progress),
            )
            clip_progress.close()
            write_json(output_dir / "mock_clips_result.json", clip_result)
            pipeline_progress.write(f"Wrote mock clip result: {clip_result['created_clip_count']} clips")
        else:
            pipeline_progress.write("Generating Veo clips")
            veo_options = VeoGenerationOptions(
                model=args.veo_model,
                aspect_ratio=args.aspect_ratio,
                resolution=args.resolution,
                person_generation=args.person_generation,
                poll_interval_seconds=args.veo_poll_interval,
                max_polls=args.veo_max_polls,
                limit=args.veo_limit,
                skip_existing=not args.overwrite_existing,
                continuity_enabled=not args.no_continuity,
                continuity_scope=args.continuity_scope,
            )
            clip_jobs = artifacts["veo_manifest"].get("jobs", [])
            clip_progress = pipeline_progress.child(len(clip_jobs), "Veo clips")
            clip_result = generate_veo_clips_from_manifest(
                veo_manifest=artifacts["veo_manifest"],
                media_root=output_dir,
                options=veo_options,
                persist_manifest=lambda payload: write_json(output_dir / "veo_manifest.json", payload),
                progress=_progress_callback(clip_progress),
            )
            clip_progress.close()
            write_json(output_dir / "veo_generation_result.json", clip_result)
            pipeline_progress.write(
                "Wrote Veo generation result: "
                f"{clip_result['generated_clip_count']} generated, "
                f"{clip_result['skipped_clip_count']} skipped, "
                f"{clip_result['failed_clip_count']} failed"
            )

            missing_job_ids = _incomplete_veo_job_ids(artifacts["veo_manifest"], output_dir)
            if missing_job_ids and args.veo_limit is not None:
                raise SystemExit(
                    "Skipping stitching because --veo-limit left clips incomplete: "
                    f"{_format_job_id_sample(missing_job_ids)}"
                )
            for retry_index in range(max(0, args.veo_retry_missing_attempts)):
                if not missing_job_ids:
                    break
                pipeline_progress.write(
                    "Retrying missing or failed Veo clips before stitching "
                    f"(attempt {retry_index + 1}/{args.veo_retry_missing_attempts}): "
                    f"{_format_job_id_sample(missing_job_ids)}"
                )
                retry_options = replace(
                    veo_options,
                    limit=None,
                    failed_only=False,
                    job_ids=tuple(missing_job_ids),
                )
                retry_progress = pipeline_progress.child(len(clip_jobs), "Veo retry")
                retry_result = generate_veo_clips_from_manifest(
                    veo_manifest=artifacts["veo_manifest"],
                    media_root=output_dir,
                    options=retry_options,
                    persist_manifest=lambda payload: write_json(output_dir / "veo_manifest.json", payload),
                    progress=_progress_callback(retry_progress),
                )
                retry_progress.close()
                write_json(output_dir / "veo_generation_retry_result.json", retry_result)
                missing_job_ids = _incomplete_veo_job_ids(artifacts["veo_manifest"], output_dir)

            if missing_job_ids:
                raise SystemExit(
                    "Skipping stitching because Veo clips are still incomplete after retry: "
                    f"{_format_job_id_sample(missing_job_ids)}"
                )
        pipeline_progress.update("Clip generation")

        pipeline_progress.write("Stitching episode and chapter videos")
        stitch_manifest = read_json(output_dir / "stitch_manifest.json")
        stitch_result = stitch_from_manifest(
            stitch_manifest=stitch_manifest,
            media_root=output_dir,
            output_root=output_dir,
            include_chapter=not args.episodes_only,
            copy_codecs=args.copy_codecs,
        )
        write_json(output_dir / "stitch_result.json", stitch_result)
        pipeline_progress.update("Stitching")
        pipeline_progress.write(f"Completed pipeline; wrote artifacts and videos under {output_dir}")
        pipeline_progress.close()
    elif args.command == "plan":
        chapter_path = Path(args.chapter_json)
        output_dir = Path(args.output_dir)
        progress = ProgressTracker(total=2, description="Plan")
        progress.write(f"Reading chapter extraction: {chapter_path}")
        chapter = read_json(chapter_path)
        progress.update("Read chapter")
        progress.write("Building planning artifacts")
        artifacts = build_planning_artifacts(
            chapter,
            target_episode_count=args.episode_count,
            clips_per_episode=args.clips_per_episode,
            clip_duration_seconds=args.clip_duration,
        )

        output_dir.mkdir(parents=True, exist_ok=True)
        write_json(output_dir / "episode_plan.json", artifacts["episode_plan"])
        write_json(output_dir / "storyboard.json", artifacts["storyboard"])
        write_json(output_dir / "veo_manifest.json", artifacts["veo_manifest"])
        write_json(output_dir / "stitch_manifest.json", artifacts["stitch_manifest"])

        progress.update("Write planning artifacts")
        progress.write(
            f"Wrote planning artifacts to {output_dir}: "
            f"{artifacts['episode_plan']['episode_count']} episodes, "
            f"{artifacts['storyboard']['clip_count']} clips"
        )
        progress.close()
    elif args.command == "extract-datalab":
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        progress = ProgressTracker(total=2, description="Extract")
        progress.write(f"Output directory: {output_dir}")

        if args.raw_json:
            progress.write(f"Reading saved Datalab response: {args.raw_json}")
            datalab_result = read_json(Path(args.raw_json))
            source_pdf = args.pdf or datalab_result.get("source_pdf") or "unknown.pdf"
        else:
            if not args.pdf:
                parser.error("--pdf is required unless --raw-json is provided")
            api_key = os.environ.get("DATALAB_API_KEY", "")
            client = DatalabConvertClient(api_key=api_key)
            options = DatalabConvertOptions(
                output_format="json",
                mode=args.mode,
                paginate=True,
                disable_image_extraction=False,
                disable_image_captions=False,
                max_pages=args.max_pages,
                page_range=args.page_range,
                skip_cache=args.skip_cache,
            )
            datalab_progress = progress.child(args.max_polls, "Datalab polling")
            datalab_result = client.convert_pdf(
                Path(args.pdf),
                options=options,
                poll_interval_seconds=args.poll_interval,
                max_polls=args.max_polls,
                progress=_progress_callback(datalab_progress),
            )
            datalab_progress.close()
            source_pdf = args.pdf
            write_json(output_dir / "raw_datalab_convert.json", datalab_result)
            progress.write(f"Wrote raw Datalab response: {output_dir / 'raw_datalab_convert.json'}")
        progress.update("Datalab response")

        progress.write("Normalizing Datalab response into chapter extraction")
        chapter = normalize_datalab_convert_result(
            datalab_result=datalab_result,
            source_pdf=source_pdf,
            output_dir=output_dir,
            chapter_id=args.chapter_id,
            chapter_title=args.chapter_title,
        )
        write_json(output_dir / "chapter_extraction.json", chapter)
        progress.update("Chapter extraction")
        progress.write(
            f"Wrote Datalab chapter extraction to {output_dir / 'chapter_extraction.json'}: "
            f"{len(chapter['pages'])} pages, {len(chapter['topics'])} topics"
        )
        progress.close()
    elif args.command == "stitch":
        manifest_path = Path(args.stitch_manifest)
        progress = ProgressTracker(total=2, description="Stitch")
        progress.write(f"Reading stitch manifest: {manifest_path}")
        stitch_manifest = read_json(manifest_path)
        progress.update("Read stitch manifest")
        media_root = Path(args.media_root) if args.media_root else manifest_path.parent
        output_dir = Path(args.output_dir) if args.output_dir else manifest_path.parent

        progress.write("Running stitching" if not args.dry_run else "Planning stitching dry run")
        result = stitch_from_manifest(
            stitch_manifest=stitch_manifest,
            media_root=media_root,
            output_root=output_dir,
            dry_run=args.dry_run,
            include_chapter=not args.episodes_only,
            copy_codecs=args.copy_codecs,
        )
        write_json(output_dir / "stitch_result.json", result)
        action = "Planned" if args.dry_run else "Completed"
        progress.update("Write stitch result")
        progress.write(f"{action} stitching; wrote {output_dir / 'stitch_result.json'}")
        progress.close()
    elif args.command == "mock-clips":
        manifest_path = Path(args.veo_manifest)
        progress = ProgressTracker(total=2, description="Mock clips")
        progress.write(f"Reading Veo manifest: {manifest_path}")
        veo_manifest = read_json(manifest_path)
        progress.update("Read Veo manifest")
        media_root = Path(args.media_root) if args.media_root else manifest_path.parent
        clip_jobs = veo_manifest.get("jobs", [])
        clip_progress = progress.child(len(clip_jobs), "Mock clips")
        result = create_placeholder_clips(
            veo_manifest=veo_manifest,
            media_root=media_root,
            limit=args.limit,
            duration_override=args.duration,
            progress=_progress_callback(clip_progress),
        )
        clip_progress.close()
        write_json(media_root / "mock_clips_result.json", result)
        progress.update("Create placeholder clips")
        progress.write(f"Created {result['created_clip_count']} placeholder clips under {media_root}")
        progress.close()
    elif args.command == "generate-veo":
        manifest_path = Path(args.veo_manifest)
        progress = ProgressTracker(total=2, description="Generate Veo")
        progress.write(f"Reading Veo manifest: {manifest_path}")
        veo_manifest = read_json(manifest_path)
        progress.update("Read Veo manifest")
        media_root = Path(args.media_root) if args.media_root else manifest_path.parent
        options = VeoGenerationOptions(
            model=args.model,
            aspect_ratio=args.aspect_ratio,
            resolution=args.resolution,
            person_generation=args.person_generation,
            poll_interval_seconds=args.poll_interval,
            max_polls=args.max_polls,
            limit=args.limit,
            skip_existing=not args.overwrite_existing,
            continuity_enabled=not args.no_continuity,
            continuity_scope=args.continuity_scope,
            failed_only=args.failed_only,
            job_ids=tuple(args.job_id) if args.job_id else None,
        )

        clip_jobs = veo_manifest.get("jobs", [])
        clip_progress = progress.child(len(clip_jobs), "Veo clips")
        result = generate_veo_clips_from_manifest(
            veo_manifest=veo_manifest,
            media_root=media_root,
            options=options,
            persist_manifest=lambda payload: write_json(manifest_path, payload),
            progress=_progress_callback(clip_progress),
        )
        clip_progress.close()
        write_json(media_root / "veo_generation_result.json", result)
        progress.update("Generate Veo clips")
        progress.write(
            "Generated "
            f"{result['generated_clip_count']} clips, skipped {result['skipped_clip_count']}, "
            f"failed {result['failed_clip_count']}; wrote {media_root / 'veo_generation_result.json'}"
        )
        progress.close()


def _progress_callback(progress: ProgressTracker):
    state = {"current": 0}

    def callback(message: str, current: int | None = None, total: int | None = None) -> None:
        if current is None:
            progress.write(message)
            return
        delta = current - state["current"]
        if delta > 0:
            progress.update(message, advance=delta)
            state["current"] = current
        else:
            progress.write(message)

    return callback


def _incomplete_veo_job_ids(veo_manifest: dict[str, Any], media_root: Path) -> list[str]:
    incomplete: list[str] = []
    jobs = veo_manifest.get("jobs", [])
    if not isinstance(jobs, list):
        return incomplete
    for index, job in enumerate(jobs, start=1):
        if not isinstance(job, dict):
            continue
        job_id = str(job.get("job_id") or f"job {index}")
        output_path = _resolve_veo_output_path(media_root, job)
        if str(job.get("status", "pending")) == "failed" or not output_path.exists():
            incomplete.append(job_id)
    return incomplete


def _resolve_veo_output_path(media_root: Path, job: dict[str, Any]) -> Path:
    output_path = Path(str(job.get("output_path") or f"clips/{job.get('job_id', 'clip')}.mp4"))
    if output_path.is_absolute():
        return output_path
    return media_root / output_path


def _format_job_id_sample(job_ids: list[str], limit: int = 10) -> str:
    sample = ", ".join(job_ids[:limit])
    if len(job_ids) > limit:
        return f"{sample}, ... ({len(job_ids)} total)"
    return sample


def load_env_file(path: Path, override: bool = False) -> dict[str, str]:
    if not path.exists():
        return {}

    loaded: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            raise ValueError(f"Invalid .env line {line_number} in {path}: expected KEY=VALUE")

        key, value = line.split("=", 1)
        key = key.strip()
        value = _parse_env_value(value.strip())
        if not key:
            raise ValueError(f"Invalid .env line {line_number} in {path}: empty key")
        if override or key not in os.environ:
            os.environ[key] = value
            loaded[key] = value
    return loaded


def _parse_env_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return value


if __name__ == "__main__":
    main()
