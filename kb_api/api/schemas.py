from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginRequest(StrictModel):
    name: str = Field(min_length=1)
    password: str = Field(min_length=1)


class PasswordChange(StrictModel):
    old_password: str = Field(min_length=1)
    new_password: str = Field(min_length=8)


class SearchOptions(StrictModel):
    query: str = Field(min_length=1)
    mode: str | None = None
    top_k: int | None = Field(default=None, ge=1, le=50)
    rerank: bool | None = None
    rerank_fetch_k: int | None = Field(default=None, ge=1, le=100)
    rrf_k: int | None = Field(default=None, ge=1, le=1000)
    file_ids: list[str] | None = None

    @model_validator(mode="after")
    def validate_options(self):
        if self.mode is not None and self.mode not in {"dense", "sparse", "hybrid"}:
            raise ValueError("mode must be dense, sparse, or hybrid")
        if self.rerank is not False and self.rerank_fetch_k is not None and self.top_k is not None and self.rerank_fetch_k < self.top_k:
            raise ValueError("rerank_fetch_k must be >= top_k")
        if self.file_ids is not None and not self.file_ids:
            raise ValueError("file_ids cannot be empty")
        if self.file_ids is not None and len(self.file_ids) > 1000:
            raise ValueError("file_ids exceeds max limit: 1000")
        return self


class SearchRequest(SearchOptions):
    workspace_ids: list[str] | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_workspaces(self):
        if self.workspace_ids is not None and not self.workspace_ids:
            raise ValueError("workspace_ids cannot be empty")
        return self


class AppCreate(StrictModel):
    app_id: str = Field(min_length=2, max_length=64, pattern=r"^[A-Za-z][A-Za-z0-9_]*$")
    name: str = Field(min_length=1, max_length=200)


class AppUpdate(StrictModel):
    name: str = Field(min_length=1, max_length=200)


class WorkspaceCreate(StrictModel):
    name: str = Field(min_length=1, max_length=200)


class WorkspaceUpdate(StrictModel):
    name: str = Field(min_length=1, max_length=200)


class WorkspaceMemberCreate(StrictModel):
    type: Literal["user", "org"]
    id: str = Field(min_length=1)
    role: Literal["admin", "editor", "viewer"]

    @model_validator(mode="after")
    def validate_role(self):
        if self.type == "org" and self.role == "admin":
            raise ValueError("Organizations cannot be workspace administrators")
        return self


class WorkspaceMemberUpdate(StrictModel):
    role: Literal["admin", "editor", "viewer"]


class OrgCreate(StrictModel):
    parent_id: str
    name: str = Field(min_length=1, max_length=200)


class OrgUpdate(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    parent_id: str | None = None
    deleted_at: None = None


class UserCreate(StrictModel):
    org_id: str | None = None
    name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=8)
    role: Literal["owner", "admin", "member"] = "member"

    @model_validator(mode="after")
    def validate_org(self):
        if (self.role == "owner") != (self.org_id is None):
            raise ValueError("owner must not belong to an org and other roles require org_id")
        return self


class UserUpdate(StrictModel):
    org_id: str | None = None
    password: str | None = Field(default=None, min_length=8)
    role: Literal["owner", "admin", "member"] | None = None
    deleted_at: None = None


class FileUploadWorkspaceRequest(StrictModel):
    file_id: str | None = None
    filename: str = Field(min_length=1, max_length=1024)
    content_type: str | None = Field(default=None, max_length=255)


class FileUploadWorkspaceComplete(StrictModel):
    object_key: str = Field(min_length=1)
    filename: str = Field(min_length=1, max_length=1024)
    content_type: str | None = Field(default=None, max_length=255)
