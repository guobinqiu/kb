from __future__ import annotations

from dataclasses import dataclass, field


from kb_api.rag_indexer.common.config import RetryConfig


@dataclass(frozen=True)
class MineruApiServerConfig:
    enable: bool = False
    base_url: str = "http://mineru-api-server:8000"
    timeout: int = 300
    tier: str = "standard"
    parse_method: str = "auto"
    retry: RetryConfig = field(default_factory=RetryConfig)


@dataclass(frozen=True)
class MineruCloudParserConfig:
    enable: bool = False
    base_url: str = "https://mineru.net"
    timeout: int = 300
    model_version: str = "vlm"
    enable_formula: bool = True
    enable_table: bool = True
    language: str = "ch"
    retry: RetryConfig = field(default_factory=RetryConfig)
    api_key: str | None = field(default=None, repr=False)


@dataclass(frozen=True, init=False)
class ParserConfig:
    download_timeout: int = 60
    mineru_cloud: MineruCloudParserConfig = field(default_factory=MineruCloudParserConfig)
    mineru: MineruApiServerConfig = field(default_factory=MineruApiServerConfig)
    active: str = "mineru"

    def __init__(
        self,
        active: str = "mineru",
        download_timeout: int = 60,
        mineru_cloud: MineruCloudParserConfig | None = None,
        mineru: MineruApiServerConfig | None = None,
    ):
        object.__setattr__(self, "download_timeout", download_timeout)
        object.__setattr__(self, "mineru_cloud", mineru_cloud or MineruCloudParserConfig())
        object.__setattr__(self, "mineru", mineru or MineruApiServerConfig())
        object.__setattr__(self, "active", active)
