from __future__ import annotations

from langchain_core.messages import HumanMessage

from chat.src.agent.llm import get_llm


_PROMPT = """根据以下对话，将最后一个用户问题改写成脱离上下文也能独立理解的检索问题。
补全代词、省略对象、人数、时间和条件，但不要添加对话中不存在的信息。
不要回答问题。如果最后一个问题已经完整，原样返回。只输出改写后的问题。

对话：
{conversation}"""


def _message_content(message) -> str:
    return message.content if isinstance(message.content, str) else str(message.content)


async def query_rewrite_node(state: dict) -> dict[str, str]:
    messages = state.get("messages") or []
    human_messages = [message for message in messages if getattr(message, "type", None) == "human"]
    if not human_messages:
        return {"search_query": ""}

    current_question = _message_content(human_messages[-1]).strip()
    if len(human_messages) == 1:
        return {"search_query": current_question}

    conversation = []
    for message in messages[-6:]:
        role = "用户" if getattr(message, "type", None) == "human" else "助手"
        conversation.append(f"{role}：{_message_content(message)}")

    try:
        response = await get_llm().ainvoke([
            HumanMessage(content=_PROMPT.format(conversation="\n".join(conversation)))
        ])
        rewritten = _message_content(response).strip()
    except Exception:
        rewritten = ""

    return {"search_query": rewritten or current_question}
