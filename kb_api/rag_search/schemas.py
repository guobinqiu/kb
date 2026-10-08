from pydantic import BaseModel, ConfigDict, Field, model_validator


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=1)
    app_id: str = Field(..., min_length=2, max_length=40)
    mode: str | None = None
    top_k: int | None = Field(None, ge=1, le=50)
    rerank: bool | None = None
    fetch_k: int | None = Field(None, ge=1, le=100)
    rrf_k: int | None = Field(None, ge=1, le=1000)
    file_ids: list[str] | None = None
    workspace_ids: list[str]

    @model_validator(mode="after")
    def validate_options(self):
        if self.mode is not None and self.mode not in {"dense", "sparse", "hybrid"}:
            raise ValueError("mode must be dense, sparse, or hybrid")
        if self.fetch_k is not None and self.top_k is not None and self.fetch_k < self.top_k:
            raise ValueError("fetch_k must be >= top_k")
        if self.file_ids is not None and not self.file_ids:
            raise ValueError("file_ids cannot be empty")
        if self.file_ids is not None and len(self.file_ids) > 1000:
            raise ValueError("file_ids exceeds max limit: 1000")
        if not self.workspace_ids:
            raise ValueError("workspace_ids cannot be empty")
        return self
