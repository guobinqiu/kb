import re
from typing import Annotated

from pydantic import AfterValidator, BaseModel

_THREAD_ID_RE = re.compile(r"^[a-zA-Z0-9_\-]+$")


def _validate_thread_id(v: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError("thread_id 不能为空")
    if len(v) > 64:
        raise ValueError("thread_id 最长 64 个字符")
    if not _THREAD_ID_RE.match(v):
        raise ValueError("thread_id 只允许字母、数字、- 和 _")
    return v


def _validate_message(v: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError("消息不能为空")
    if len(v) > 2000:
        raise ValueError("消息最长 2000 个字符")
    return v


ThreadId = Annotated[str, AfterValidator(_validate_thread_id)]
Message = Annotated[str, AfterValidator(_validate_message)]


class AgentRequest(BaseModel):
    thread_id: ThreadId
    message: Message
