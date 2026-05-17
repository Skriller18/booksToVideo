from __future__ import annotations

import json
import mimetypes
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib import error, request


DEFAULT_DATALAB_BASE_URL = "https://www.datalab.to/api/v1"
DATALAB_USER_AGENT = "books-to-video/0.1 datalab-rest-client"


@dataclass(frozen=True)
class DatalabConvertOptions:
    output_format: str = "json"
    mode: str = "accurate"
    paginate: bool = True
    disable_image_extraction: bool = False
    disable_image_captions: bool = False
    max_pages: int | None = None
    page_range: str | None = None
    skip_cache: bool = False


class DatalabClientError(RuntimeError):
    pass


class DatalabConvertClient:
    """Minimal REST client for Datalab's /convert API.

    The official docs recommend the Python SDK, but this client keeps the MVP
    dependency-free and mirrors the same submit-then-poll flow.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_DATALAB_BASE_URL,
        timeout_seconds: int = 60,
    ) -> None:
        if not api_key:
            raise DatalabClientError("DATALAB_API_KEY is required")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def convert_pdf(
        self,
        pdf_path: Path,
        options: DatalabConvertOptions,
        poll_interval_seconds: int = 2,
        max_polls: int = 300,
        progress: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        if progress:
            progress(f"Submitting {pdf_path.name} to Datalab Convert", None, None)
        submit_result = self.submit_convert(pdf_path, options)
        check_url = submit_result.get("request_check_url")
        if not check_url:
            raise DatalabClientError(f"Datalab response did not include request_check_url: {submit_result}")
        if progress:
            request_id = submit_result.get("request_id", "unknown")
            progress(f"Datalab accepted request {request_id}; polling for completion", None, None)
        return self.poll(
            check_url,
            poll_interval_seconds=poll_interval_seconds,
            max_polls=max_polls,
            progress=progress,
        )

    def submit_convert(self, pdf_path: Path, options: DatalabConvertOptions) -> dict[str, Any]:
        if not pdf_path.exists():
            raise DatalabClientError(f"PDF does not exist: {pdf_path}")

        fields = {
            "output_format": options.output_format,
            "mode": options.mode,
            "paginate": _bool(options.paginate),
            "disable_image_extraction": _bool(options.disable_image_extraction),
            "disable_image_captions": _bool(options.disable_image_captions),
            "skip_cache": _bool(options.skip_cache),
        }
        if options.max_pages is not None:
            fields["max_pages"] = str(options.max_pages)
        if options.page_range:
            fields["page_range"] = options.page_range

        body, content_type = _build_multipart_body(
            fields=fields,
            file_field="file",
            file_path=pdf_path,
        )
        req = request.Request(
            f"{self.base_url}/convert",
            data=body,
            method="POST",
            headers={
                "X-Api-Key": self.api_key,
                "User-Agent": DATALAB_USER_AGENT,
                "Accept": "application/json",
                "Content-Type": content_type,
            },
        )
        return _read_json_response(req, timeout=self.timeout_seconds)

    def poll(
        self,
        check_url: str,
        poll_interval_seconds: int,
        max_polls: int,
        progress: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        req = request.Request(
            check_url,
            method="GET",
            headers={
                "X-Api-Key": self.api_key,
                "User-Agent": DATALAB_USER_AGENT,
                "Accept": "application/json",
            },
        )
        last_result: dict[str, Any] = {}
        for poll_index in range(1, max_polls + 1):
            last_result = _read_json_response(req, timeout=self.timeout_seconds)
            status = last_result.get("status")
            if progress:
                progress(f"status={status or 'unknown'}", poll_index, max_polls)
            if status == "complete":
                if not last_result.get("success", True):
                    raise DatalabClientError(last_result.get("error") or "Datalab conversion failed")
                return last_result
            if status == "failed":
                raise DatalabClientError(last_result.get("error") or "Datalab conversion failed")
            time.sleep(poll_interval_seconds)
        raise DatalabClientError(f"Datalab conversion did not complete after {max_polls} polls: {last_result}")


def _build_multipart_body(
    fields: dict[str, str],
    file_field: str,
    file_path: Path,
) -> tuple[bytes, str]:
    boundary = f"----book-to-video-{uuid.uuid4().hex}"
    lines: list[bytes] = []

    for name, value in fields.items():
        lines.extend(
            [
                f"--{boundary}".encode("utf-8"),
                f'Content-Disposition: form-data; name="{name}"'.encode("utf-8"),
                b"",
                value.encode("utf-8"),
            ]
        )

    mime_type = mimetypes.guess_type(str(file_path))[0] or "application/pdf"
    file_bytes = file_path.read_bytes()
    lines.extend(
        [
            f"--{boundary}".encode("utf-8"),
            (
                f'Content-Disposition: form-data; name="{file_field}"; '
                f'filename="{file_path.name}"'
            ).encode("utf-8"),
            f"Content-Type: {mime_type}".encode("utf-8"),
            b"",
            file_bytes,
            f"--{boundary}--".encode("utf-8"),
            b"",
        ]
    )
    return b"\r\n".join(lines), f"multipart/form-data; boundary={boundary}"


def _read_json_response(req: request.Request, timeout: int) -> dict[str, Any]:
    try:
        with request.urlopen(req, timeout=timeout) as response:
            payload = response.read().decode("utf-8")
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise DatalabClientError(f"Datalab HTTP {exc.code}: {body}") from exc
    except error.URLError as exc:
        raise DatalabClientError(f"Could not reach Datalab: {exc.reason}") from exc

    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise DatalabClientError(f"Datalab returned non-JSON response: {payload[:500]}") from exc


def _bool(value: bool) -> str:
    return "true" if value else "false"
ProgressCallback = Callable[[str, int | None, int | None], None]
