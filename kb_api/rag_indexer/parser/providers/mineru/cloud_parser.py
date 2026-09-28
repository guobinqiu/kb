import io
import json
import time
import zipfile

import httpx

from kb_api.rag_indexer.parser.common.schema import Block
from kb_api.rag_indexer.parser.providers.mineru.normalizer import content_list_to_blocks
from kb_api.rag_indexer.parser.common.config import MineruCloudParserConfig
from kb_api.rag_indexer.parser.common.retry import retry_call
from kb_api.rag_indexer.parser.common.upstream import UpstreamServiceError, upstream_error


class MineruCloudDocumentParser:
    def __init__(self, config: MineruCloudParserConfig, *, http_client: httpx.Client | None = None):
        self.config = config
        self._client = http_client
        self.ready = False

    def start(self) -> None:
        if not self.config.api_key:
            raise ValueError("MINERU_API_KEY is required")
        if self._client is None:
            self._client = httpx.Client(follow_redirects=True)
        self.ready = True

    def stop(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
        self.ready = False

    def parse_url(self, presigned_url: str) -> list[Block]:
        if not self.ready:
            self.start()
        deadline = time.monotonic() + self.config.timeout
        base = self.config.base_url.rstrip("/")
        headers = {"Authorization": f"Bearer {self.config.api_key}"}
        task = self._data(self._request("POST", f"{base}/api/v4/extract/task", deadline, headers=headers, json={
            "url": presigned_url,
            "model_version": self.config.model_version,
            "enable_formula": self.config.enable_formula,
            "enable_table": self.config.enable_table,
            "language": self.config.language,
        }))
        while True:
            result = self._data(self._request("GET", f"{base}/api/v4/extract/task/{task['task_id']}", deadline, headers=headers))
            if result["state"] == "done":
                break
            if result["state"] == "failed":
                raise UpstreamServiceError(service="parser", error=result.get("err_msg"), retryable=False, status_code=502)
            if result["state"] not in {"pending", "running", "converting"}:
                raise ValueError(f"Unknown MinerU task state: {result['state']}")
            time.sleep(min(3.0, self._remaining(deadline)))
        response = self._request("GET", result["full_zip_url"], deadline)
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            names = sorted(name for name in archive.namelist() if name.endswith("_content_list.json") or name == "content_list.json")
            if len(names) != 1:
                raise ValueError("MinerU result must contain one content_list.json")
            blocks = content_list_to_blocks(json.loads(archive.read(names[0])))
        if not blocks:
            raise ValueError("MinerU returned empty parse result")
        return blocks

    def _request(self, method: str, url: str, deadline: float, **kwargs) -> httpx.Response:
        def send():
            try:
                response = self._client.request(method, url, timeout=self._remaining(deadline), **kwargs)
                response.raise_for_status()
                return response
            except httpx.HTTPError as exc:
                raise upstream_error("parser", exc, retryable=True) from exc

        return retry_call(send, self.config.retry, operation_name="parser.mineru_cloud.request")

    @staticmethod
    def _remaining(deadline: float) -> float:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise UpstreamServiceError(service="parser", error="MinerU parsing timed out", retryable=False, status_code=504)
        return remaining

    @staticmethod
    def _data(response: httpx.Response) -> dict:
        body = response.json()
        if body["code"] != 0:
            raise UpstreamServiceError(service="parser", error=body.get("msg"), retryable=False, status_code=502)
        return body["data"]
