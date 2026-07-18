from __future__ import annotations

from pathlib import Path
from typing import Any

_CHUNK_SIZE = 5 * 1024 * 1024


class PresageError(RuntimeError):
    pass


class PresagePhysiologyClient:
    """Minimal Presage Physiology API client.

    Speaks the same REST protocol as the official `presage-technologies`
    package (multipart upload to presigned URLs, then poll `/retrieve-data`),
    but without that package's pinned old mediapipe dependency: clips are
    uploaded raw and preprocessed server-side.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.physiology.presagetech.com",
        timeout: float = 30.0,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {"x-api-key": self.api_key}

    def queue_processing_hr_rr(self, video_path: str) -> str:
        import requests

        target = Path(video_path)
        response = requests.post(
            f"{self.base_url}/v1/upload-url",
            headers=self._headers(),
            json={"file_size": target.stat().st_size, "hr_br": {"to_process": True}},
            timeout=self.timeout,
        )
        if response.status_code == 401:
            raise PresageError("Presage rejected the API key")
        response.raise_for_status()
        body = response.json()
        video_id, upload_id, urls = body["id"], body["upload_id"], body["urls"]

        parts = []
        with target.open("rb") as handle:
            for number, url in enumerate(urls, start=1):
                chunk = handle.read(_CHUNK_SIZE)
                put_response = requests.put(url, data=chunk, timeout=self.timeout)
                put_response.raise_for_status()
                parts.append({"ETag": put_response.headers["ETag"], "PartNumber": number})

        requests.post(
            f"{self.base_url}/v1/complete",
            headers=self._headers(),
            json={"id": video_id, "upload_id": upload_id, "parts": parts},
            timeout=self.timeout,
        ).raise_for_status()
        return video_id

    def retrieve_result(self, video_id: str) -> Any | None:
        """One poll attempt; returns the payload when ready, otherwise None."""
        import requests

        response = requests.post(
            f"{self.base_url}/retrieve-data",
            headers=self._headers(),
            json={"id": video_id, "reshape": False},
            timeout=self.timeout,
        )
        if response.status_code == 200:
            return response.json()
        if response.status_code == 401:
            raise PresageError("Presage rejected the API key")
        return None
