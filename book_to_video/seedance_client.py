from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path
from typing import Any

import requests

from .veo_client import VeoGenerationError, VeoGenerationOptions


OPENROUTER_API_BASE = "https://openrouter.ai/api/v1"


class OpenRouterSeedanceClient:
    """Duck-typed video generator client for OpenRouter Seedance 2.0.

    Implements the same interface expected by veo_client.generate_veo_clips_from_manifest:
      - submit_video_generation(job, options, start_frame_path)
      - poll_video_generation(operation, options)
      - save_generated_video(operation, output_path)
    """

    def __init__(self, api_key: str | None = None, base_url: str = OPENROUTER_API_BASE) -> None:
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
        if not self.api_key:
            raise VeoGenerationError(
                "OPENROUTER_API_KEY is required for OpenRouter Seedance generation"
            )
        self.base_url = base_url.rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------ #
    #  Duck-typed interface expected by veo_client.py
    # ------------------------------------------------------------------ #

    def submit_video_generation(
        self,
        job: dict[str, Any],
        options: VeoGenerationOptions,
        start_frame_path: Path | None = None,
    ) -> dict[str, Any]:
        """Submit a video generation request to OpenRouter and return a lightweight operation handle."""
        payload = self._build_payload(job, options, start_frame_path)
        url = f"{self.base_url}/videos"
        try:
            response = requests.post(url, headers=self.headers, data=json.dumps(payload), timeout=60)
            response.raise_for_status()
        except requests.exceptions.RequestException as exc:
            raise VeoGenerationError(
                f"OpenRouter submit failed for {job.get('job_id', 'unknown job')}: {exc}"
            ) from exc

        data = response.json()
        job_id = data.get("id")
        if not job_id:
            raise VeoGenerationError(
                f"OpenRouter submit response missing 'id' for {job.get('job_id', 'unknown job')}: {data}"
            )

        return {
            "job_id": job_id,
            "polling_url": f"{self.base_url}/videos/{job_id}",
            "_openrouter_response": data,
        }

    def poll_video_generation(
        self,
        operation: dict[str, Any],
        options: VeoGenerationOptions,
    ) -> dict[str, Any]:
        """Poll OpenRouter until the video job completes or max_polls is reached."""
        polling_url = operation.get("polling_url")
        job_id = operation.get("job_id", "unknown")
        if not polling_url:
            raise VeoGenerationError(f"OpenRouter operation missing polling_url for job {job_id}")

        for _ in range(options.max_polls):
            try:
                response = requests.get(polling_url, headers=self.headers, timeout=30)
                response.raise_for_status()
            except requests.exceptions.RequestException as exc:
                raise VeoGenerationError(f"OpenRouter poll failed for job {job_id}: {exc}") from exc

            data = response.json()
            status = data.get("status", "")

            if status == "completed":
                result = data.get("result") or {}
                video_url = result.get("url")
                if not video_url:
                    raise VeoGenerationError(
                        f"OpenRouter job {job_id} completed but result.url is missing"
                    )
                return {
                    "job_id": job_id,
                    "polling_url": polling_url,
                    "done": True,
                    "response": {"url": video_url, "_raw": data},
                }
            elif status == "failed":
                raise VeoGenerationError(
                    f"OpenRouter job {job_id} failed: {data.get('error', 'unknown error')}"
                )

            time.sleep(options.poll_interval_seconds)

        raise VeoGenerationError(
            f"OpenRouter job {job_id} did not complete after {options.max_polls} polls"
        )

    def save_generated_video(
        self,
        operation: dict[str, Any],
        output_path: Path,
    ) -> None:
        """Download the completed video from OpenRouter to output_path."""
        result = (
            operation.get("response") or {}
        )
        video_url = result.get("url") if isinstance(result, dict) else None
        if not video_url:
            raise VeoGenerationError(
                f"OpenRouter operation missing video url for job {operation.get('job_id')}"
            )

        try:
            with requests.get(video_url, stream=True, timeout=120) as stream:
                stream.raise_for_status()
                output_path.parent.mkdir(parents=True, exist_ok=True)
                with open(output_path, "wb") as file:
                    for chunk in stream.iter_content(chunk_size=8192):
                        if chunk:
                            file.write(chunk)
        except requests.exceptions.RequestException as exc:
            raise VeoGenerationError(
                f"Failed to download OpenRouter video for job {operation.get('job_id')}: {exc}"
            ) from exc

    # ------------------------------------------------------------------ #
    #  Helpers
    # ------------------------------------------------------------------ #

    def _build_payload(
        self,
        job: dict[str, Any],
        options: VeoGenerationOptions,
        start_frame_path: Path | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": options.model,
            "prompt": job.get("prompt", ""),
            "generate_audio": True,
        }
        if options.aspect_ratio:
            payload["aspect_ratio"] = options.aspect_ratio
        if options.resolution:
            payload["resolution"] = options.resolution
        duration_seconds = job.get("duration_seconds")
        if duration_seconds is not None:
            payload["duration"] = int(duration_seconds)

        if start_frame_path and start_frame_path.exists():
            frame_images = self._build_frame_images(start_frame_path)
            if frame_images:
                payload["frame_images"] = frame_images

        return payload

    def _build_frame_images(self, start_frame_path: Path) -> list[dict]:
        try:
            image_bytes = start_frame_path.read_bytes()
            # Create data URL PNG
            b64 = base64.b64encode(image_bytes).decode("ascii")
            data_url = f"data:image/png;base64,{b64}"
            return [{"type": "first_frame", "image": data_url}]
        except Exception as exc:
            raise VeoGenerationError(
                f"Failed to read continuity frame {start_frame_path}: {exc}"
            ) from exc
