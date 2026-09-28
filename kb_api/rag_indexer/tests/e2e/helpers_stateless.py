import os
import socket
import subprocess
import sys
import threading
import time
import uuid
from contextlib import ExitStack
from dataclasses import dataclass, field
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest
import yaml

from kb_api.rag_indexer.core.scope import collection_name_for_app


ROOT = Path(__file__).resolve().parents[4]


@dataclass
class StatelessServer:
    client: httpx.Client = field(repr=False)
    apps: tuple[httpx.Client, httpx.Client] = field(repr=False)
    app_ids: tuple[str, str]
    source_dir: Path
    source_url: str

    def document(self, name: str, content: str) -> dict:
        (self.source_dir / name).write_text(content, encoding="utf-8")
        return {
            "presigned_url": f"{self.source_url}/{name}",
            "s3_url": f"s3://caller-owned/{name}",
            "filename": name,
        }


@pytest.fixture(scope="module")
def stateless_rag(tmp_path_factory):
    workdir = tmp_path_factory.mktemp("rag-stateless")
    raw = yaml.safe_load((ROOT / "kb_api/config/rag.yaml").read_text())
    for config in raw["db"].values():
        config["enable"] = False
        config.pop("url", None)
    for name in ("qdrant", "milvus", "qdrant_cloud", "milvus_cloud"):
        raw["vector_db"][name]["enable"] = name == "milvus"
    raw["chunking"]["text"] = {"chunk_size": 256, "chunk_overlap": 0}
    raw["storage"]["endpoint_url"] = ""
    raw["auth"]["admin"] = {}

    credentials = [
        {"app_id": "e2e_stateless_" + uuid.uuid4().hex, "api_key": uuid.uuid4().hex}
        for _ in range(2)
    ]
    collection_names = tuple(collection_name_for_app(item["app_id"]) for item in credentials)
    env = dict(os.environ)
    for name in (
        "DATABASE_URL", "S3_ACCESS_KEY", "S3_SECRET_KEY",
        "S3_SESSION_TOKEN", "RAG_ADMIN_PASSWORD",
    ):
        env.pop(name, None)
    raw["auth"]["apps"] = credentials
    env["NO_PROXY"] = ",".join(filter(None, [env.get("NO_PROXY"), "127.0.0.1", "localhost"]))
    env["no_proxy"] = env["NO_PROXY"]

    config_path = workdir / "rag.yaml"
    config_path.touch(mode=0o600)
    config_path.write_text(yaml.safe_dump(raw))
    env["KB_CONFIG_FILE"] = str(config_path)
    source_dir = workdir / "source"
    source_dir.mkdir()
    log_path = workdir / "rag.log"
    log_path.touch(mode=0o600)
    process = None
    try:
        with ThreadingHTTPServer(
            ("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(source_dir)),
        ) as source:
            thread = threading.Thread(target=source.serve_forever, daemon=True)
            thread.start()
            try:
                with socket.socket() as listener, log_path.open("w") as log, ExitStack() as clients:
                    listener.bind(("127.0.0.1", 0))
                    listener.listen()
                    address = f"http://127.0.0.1:{listener.getsockname()[1]}"
                    process = subprocess.Popen(
                        [sys.executable, "-m", "uvicorn", "kb_api.rag_indexer.app.main:app",
                         "--fd", str(listener.fileno()), "--no-access-log"],
                        cwd=ROOT, env=env, pass_fds=(listener.fileno(),), stdout=log, stderr=log,
                    )
                    client = clients.enter_context(httpx.Client(base_url=address, timeout=180, trust_env=False))
                    deadline = time.monotonic() + 60
                    while time.monotonic() < deadline:
                        if process.poll() is not None:
                            pytest.fail(f"Stateless RAG exited during startup; inspect {log_path}")
                        try:
                            if client.get("/health", timeout=1).status_code == 200:
                                break
                        except httpx.TransportError:
                            pass
                        time.sleep(0.2)
                    else:
                        pytest.fail(f"Stateless RAG startup timed out; inspect {log_path}")
                    app_clients = tuple(
                        clients.enter_context(httpx.Client(
                            base_url=address, timeout=180, trust_env=False,
                            headers={"Authorization": f"Bearer {credential['api_key']}"},
                        ))
                        for credential in credentials
                    )
                    yield StatelessServer(
                        client, app_clients, tuple(item["app_id"] for item in credentials),
                        source_dir, f"http://127.0.0.1:{source.server_port}",
                    )
            finally:
                try:
                    if process is not None:
                        process.terminate()
                        try:
                            process.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait()
                finally:
                    source.shutdown()
                    thread.join(timeout=10)
    finally:
        try:
            if process is not None:
                from pymilvus import MilvusClient

                vector = MilvusClient(
                    uri=raw["vector_db"]["milvus"]["base_url"], token=env.get("MILVUS_TOKEN", ""), timeout=30,
                )
                try:
                    for collection in collection_names:
                        if vector.has_collection(collection):
                            vector.drop_collection(collection)
                finally:
                    vector.close()
        finally:
            config_path.unlink(missing_ok=True)
