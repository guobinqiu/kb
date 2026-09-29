import mimetypes
import time
from pathlib import Path
from urllib.parse import urljoin

import httpx

from kb_api.rag_indexer.parser.common.config import MineruApiServerConfig, RetryConfig
from kb_api.rag_indexer.common.retry import retry_call
from kb_api.rag_indexer.parser.common.schema import Block
from kb_api.rag_indexer.common.upstream import UpstreamServiceError, upstream_error
from kb_api.rag_indexer.parser.common.validation import InvalidDocumentError
from kb_api.rag_indexer.parser.providers.mineru.normalizer import structured_content_to_blocks


class MineruApiDocumentParser:
    def __init__(self, config: MineruApiServerConfig, http_client: httpx.Client | None = None):
        self.config = config
        self._client = http_client
        self.ready = False

    def start(self) -> None:
        if self._client is None:
            self._client = httpx.Client(follow_redirects=True)
        self.ready = True

    def stop(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
        self.ready = False

    def parse_file(self, filepath: str, original_filename: str | None = None) -> list[Block]:
        deadline = time.monotonic() + self.config.timeout
        if not self.ready:
            self.start()
        path = Path(filepath)
        filename = original_filename or path.name
        data = path.read_bytes()
        base = self.config.base_url.rstrip("/")
        try:
            upload = self._request("POST", f"{base}/v1/uploads", deadline, json={
                "filename": filename, "bytes": len(data), "mime_type": mimetypes.guess_type(filename)[0] or "application/octet-stream", "purpose": "parse",
            }).json()
            self._request("PUT", urljoin(f"{base}/", upload["upload_url"]), deadline,
                          content=data, headers=upload["upload_headers"])
            completed = self._request("POST", f"{base}/v1/uploads/{upload['id']}/complete", deadline, json={}).json()
            job = self._request("POST", f"{base}/v1/parse/jobs", deadline, json={
                "files": [{"source": {"type": "file_id", "file_id": completed["file"]["id"]}}],
                "tier": self.config.tier, "ocr_mode": self.config.parse_method, "output_formats": ["structured_content"],
            }).json()
            job_url = f"{base}/v1/parse/jobs/{job['job_id']}"
            while job["status"] in {"queued", "running"}:
                job = self._request("GET", job_url, deadline).json()
                if job["status"] in {"queued", "running"}:
                    time.sleep(min(1.0, self._remaining(deadline)))
            if job["status"] != "completed":
                message = next((entry["error"].get("message") for entry in job.get("files", [])
                                if entry.get("error")), None)
                raise UpstreamServiceError(service="parser", error=message or f"MinerU job status: {job['status']}",
                                           retryable=False, status_code=502)
            files = job["files"]
            if len(files) != 1 or files[0]["status"] != "completed":
                raise ValueError("MinerU must return one completed file")
            output_id = files[0]["output_files"]["structured_content"]["file_id"]
            response = self._request("GET", f"{base}/v1/files/{output_id}/content", deadline)
            blocks = structured_content_to_blocks(response.json())
            self._remaining(deadline)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise upstream_error("parser", exc) from exc
        if not blocks:
            raise InvalidDocumentError(f"Empty file: {filename}")
        return blocks

    def _request(self, method: str, url: str, deadline: float, **kwargs) -> httpx.Response:
        attempts = 0

        def send():
            nonlocal attempts
            if attempts and self.config.retry.interval_seconds:
                time.sleep(min(self.config.retry.interval_seconds, self._remaining(deadline)))
            attempts += 1
            try:
                response = self._client.request(method, url, timeout=self._remaining(deadline),
                                                follow_redirects=True, **kwargs)
                response.raise_for_status()
                self._remaining(deadline)
                return response
            except httpx.HTTPError as exc:
                error = upstream_error("parser", exc, retryable=True)
                # A transport failure cannot tell us whether the POST already created a resource.
                if method == "POST" and not isinstance(exc, httpx.HTTPStatusError):
                    error.retryable = False
                raise error from exc

        return retry_call(send, RetryConfig(self.config.retry.max_attempts, 0),
                          operation_name="parser.mineru_api.request", enforce_deadline=False, logger_name="parser.retry")

    @staticmethod
    def _remaining(deadline: float) -> float:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise UpstreamServiceError(service="parser", error="MinerU parsing timed out",
                                       retryable=False, status_code=504)
        return remaining
