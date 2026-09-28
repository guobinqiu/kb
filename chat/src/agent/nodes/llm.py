import asyncio
from datetime import datetime

from langchain_core.messages import AIMessage, SystemMessage

from chat.src.agent.llm import get_llm
from chat.src.agent.stream import safe_get_writer, write_reply
from chat.src.config import settings
from chat.src.infra.metrics import Timer, mark_llm_error, mark_llm_ok

_semaphore: asyncio.Semaphore | None = None


def init_semaphore(limit: int):
    global _semaphore
    _semaphore = asyncio.Semaphore(limit)


def get_semaphore() -> asyncio.Semaphore:
    """获取并发 semaphore；未初始化时按应用配置创建。"""
    global _semaphore
    if _semaphore is None:
        limit = settings.llm_concurrency_limit
        _semaphore = asyncio.Semaphore(limit)
    return _semaphore


async def llm_node(state: dict) -> dict:
    """llm 节点：流式调用 LLM，逐 token 推送给前端。

    每轮注入配置提示词和当前时间，有 rag_context 时追加参考资料。
    """
    messages = list(state.get("messages") or [])
    rag_context = state.get("rag_context") or ""

    now = datetime.now()
    weekday = "一二三四五六日"[now.weekday()]
    system_content = (
        f"{settings.prompt.strip()}\n\n"
        f"当前时间：{now:%Y-%m-%d %H:%M:%S}，星期{weekday}。"
    )
    if rag_context:
        system_content += f"\n\n## 参考资料\n\n{rag_context}"
    messages = [SystemMessage(content=system_content)] + messages

    base_llm = get_llm()
    writer = safe_get_writer()

    full_content = ""

    async with get_semaphore():
        with Timer() as t:
            try:
                async for chunk in base_llm.astream(messages):
                    # 逐 token 推送
                    token = chunk.content
                    if token:
                        full_content += token
                        write_reply(writer, token)

                mark_llm_ok()
            except Exception as e:
                mark_llm_error(str(e))
                raise

    # 构造 AIMessage 用于 state.messages（langchain 需要完整消息对象）
    response = AIMessage(content=full_content)

    return {
        "messages": [response],
        "llm_ms": t.ms,
        "tokens_in": 0,
        "tokens_out": 0,
        "cost": 0.0,
    }
