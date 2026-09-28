from pydantic import BaseModel, ConfigDict, Field, model_validator


class EmbeddingSpecRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(..., min_length=1)
    model: str = Field(..., min_length=1)
    dimensions: int = Field(..., gt=0)


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=1)
    app_id: str | None = None
    mode: str | None = None
    top_k: int | None = Field(None, ge=1, le=50)
    rerank: bool | None = None
    rerank_fetch_k: int | None = Field(None, ge=1, le=100)
    rrf_k: int | None = Field(None, ge=1, le=1000)
    file_ids: list[str] | None = None
    workspace_ids: list[str] | None = None
    embedding: EmbeddingSpecRequest | None = None

    @model_validator(mode="after")
    def validate_file_ids(self):
        if self.mode is not None and self.mode not in {"dense", "sparse", "hybrid"}:
            raise ValueError("mode must be dense, sparse, or hybrid")
        if self.rerank is not False and self.rerank_fetch_k is not None and self.top_k is not None and self.rerank_fetch_k < self.top_k:
            raise ValueError("rerank_fetch_k must be >= top_k")
        if self.file_ids is not None and len(self.file_ids) == 0:
            raise ValueError("file_ids cannot be empty")
        if self.file_ids is not None and len(self.file_ids) > 1000:
            raise ValueError("file_ids exceeds max limit: 1000")
        if self.workspace_ids is not None and len(self.workspace_ids) == 0:
            raise ValueError("workspace_ids cannot be empty")
        return self


class FileIndexRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    presigned_url: str | None = Field(None, min_length=1)
    s3_url: str = Field(..., min_length=1)
    filename: str | None = None
    app_id: str | None = None
    file_id: str | None = Field(None, min_length=1, max_length=64)
    embedding: EmbeddingSpecRequest | None = None

    @model_validator(mode="after")
    def validate_request(self):
        if not self.s3_url.startswith("s3://"):
            raise ValueError("s3_url must start with s3://")
        return self


class PresignRequest(BaseModel):
    s3_url: str = Field(..., min_length=1)
    expires_in: int = Field(3600, ge=60, le=86400)

    @model_validator(mode="after")
    def validate_s3_url(self):
        if not self.s3_url.startswith("s3://"):
            raise ValueError("s3_url must start with s3://")
        return self


class DebugEncodeRequest(BaseModel):
    query: str = Field(..., min_length=1)


class DebugSearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    top_k: int = Field(20, ge=1, le=100)
    file_ids: list[str] | None = None

    @model_validator(mode="after")
    def validate_file_ids(self):
        if self.file_ids is not None and len(self.file_ids) == 0:
            raise ValueError("file_ids cannot be empty")
        if self.file_ids is not None and len(self.file_ids) > 1000:
            raise ValueError("file_ids exceeds max limit: 1000")
        return self
