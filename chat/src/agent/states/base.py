import operator
from typing import Annotated, TypedDict


class AgentState(TypedDict, total=False):
    """Chat graph 主 state。

    - messages: LangChain Message list，使用 operator.add reducer 累加。
    - rag_context: RAG 预检索结果上下文（覆盖式写，不使用 reducer）。
    - tool_results: 每轮工具调用结果摘要（覆盖式写，不使用 reducer）。
    - 其余字段：perf / token 计数。
    """
    messages:     Annotated[list, operator.add]
    rag_context:  str
    workspace_ids: list[str]
    tool_results: list
    llm_ms:       float
    tokens_in:    int
    tokens_out:   int
    cost:         float
