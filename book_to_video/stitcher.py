from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any


class StitcherError(RuntimeError):
    pass


def stitch_from_manifest(
    stitch_manifest: dict[str, Any],
    media_root: Path,
    output_root: Path,
    dry_run: bool = False,
    include_chapter: bool = True,
    copy_codecs: bool = False,
    ffmpeg_path: str | None = None,
) -> dict[str, Any]:
    ffmpeg = ffmpeg_path or shutil.which("ffmpeg")
    if not ffmpeg and not dry_run:
        raise StitcherError("ffmpeg is required for stitching but was not found on PATH")

    output_root.mkdir(parents=True, exist_ok=True)
    concat_dir = output_root / "_concat"
    if not dry_run:
        concat_dir.mkdir(parents=True, exist_ok=True)

    episode_results = []
    for episode in stitch_manifest.get("episodes", []):
        clip_paths = [_resolve_media_path(media_root, path) for path in episode.get("clip_paths", [])]
        output_path = _resolve_output_path(output_root, episode["output_video"])
        missing = [str(path) for path in clip_paths if not path.exists()]

        command: list[str] = []
        concat_path = concat_dir / f"{episode['episode_id']}.txt"
        if not dry_run:
            if missing:
                raise StitcherError(
                    f"Cannot stitch {episode['episode_id']}; missing clips: {', '.join(missing[:5])}"
                )
            _write_concat_file(concat_path, clip_paths)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            command = _ffmpeg_concat_command(
                ffmpeg=ffmpeg or "ffmpeg",
                concat_path=concat_path,
                output_path=output_path,
                copy_codecs=copy_codecs,
            )
            _run(command)

        episode_results.append(
            {
                "episode_id": episode["episode_id"],
                "title": episode.get("title", ""),
                "clip_count": len(clip_paths),
                "missing_clip_count": len(missing),
                "missing_clips": missing,
                "output_video": str(output_path),
                "concat_file": str(concat_path),
                "command": command,
                "status": "dry_run" if dry_run else "stitched",
            }
        )

    chapter_result = None
    playlist = stitch_manifest.get("chapter_playlist") or {}
    if include_chapter and playlist.get("output_video"):
        episode_paths = [_resolve_output_path(output_root, path) for path in playlist.get("episode_paths", [])]
        chapter_output = _resolve_output_path(output_root, playlist["output_video"])
        missing = [str(path) for path in episode_paths if not path.exists()]
        concat_path = concat_dir / "chapter_playlist.txt"
        command = []

        if not dry_run:
            if missing:
                raise StitcherError(f"Cannot stitch chapter; missing episode videos: {', '.join(missing[:5])}")
            _write_concat_file(concat_path, episode_paths)
            chapter_output.parent.mkdir(parents=True, exist_ok=True)
            command = _ffmpeg_concat_command(
                ffmpeg=ffmpeg or "ffmpeg",
                concat_path=concat_path,
                output_path=chapter_output,
                copy_codecs=copy_codecs,
            )
            _run(command)

        chapter_result = {
            "episode_count": len(episode_paths),
            "missing_episode_count": len(missing),
            "missing_episodes": missing,
            "output_video": str(chapter_output),
            "concat_file": str(concat_path),
            "command": command,
            "status": "dry_run" if dry_run else "stitched",
        }

    return {
        "dry_run": dry_run,
        "media_root": str(media_root),
        "output_root": str(output_root),
        "episode_results": episode_results,
        "chapter_result": chapter_result,
    }


def _resolve_media_path(media_root: Path, path: str) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return media_root / candidate


def _resolve_output_path(output_root: Path, path: str) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return output_root / candidate


def _write_concat_file(path: Path, media_paths: list[Path]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"file '{_escape_concat_path(item.resolve())}'" for item in media_paths]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _escape_concat_path(path: Path) -> str:
    return str(path).replace("'", "'\\''")


def _ffmpeg_concat_command(
    ffmpeg: str,
    concat_path: Path,
    output_path: Path,
    copy_codecs: bool,
) -> list[str]:
    command = [
        ffmpeg,
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_path),
    ]
    if copy_codecs:
        command.extend(["-c", "copy"])
    else:
        command.extend(
            [
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-preset",
                "veryfast",
                "-crf",
                "18",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
            ]
        )
    command.append(str(output_path))
    return command


def _run(command: list[str]) -> None:
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise StitcherError(f"ffmpeg failed with exit code {result.returncode}: {stderr}")

