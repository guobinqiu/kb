from pydantic import BaseModel, ConfigDict, Field, StrictBool


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error: str | None
    service: str | None = None
    retryable: StrictBool
    traceId: str = Field(pattern=r"^[0-9a-f]{32}$")
