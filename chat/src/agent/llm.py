import json

from langchain_openai import ChatOpenAI

from chat.src.config import settings
from chat.src.infra.model_context import get_request_model_name

_default_llm: ChatOpenAI | None = None


_llm_pool: dict[str, ChatOpenAI] = {}


def get_llm_for_model(model_name: str) -> ChatOpenAI:
    """获取指定模型的 ChatOpenAI 实例，懒创建并缓存。"""
    if model_name not in _llm_pool:
        _llm_pool[model_name] = create_llm(model=model_name)
    return _llm_pool[model_name]


def get_llm() -> ChatOpenAI:
    """返回默认共享实例（懒初始化）"""
    requested_model_name = get_request_model_name()
    if requested_model_name:
        # 请求级模型指定不应污染默认共享实例。
        return get_llm_for_model(requested_model_name)

    global _default_llm
    if _default_llm is None:
        _default_llm = create_llm()
    return _default_llm


def create_llm(
    model: str | None = None,
    timeout: int | None = None,
    max_retries: int = 0,
) -> ChatOpenAI:
    """按需创建独立实例，用于需要不同配置的场景"""
    model_name = model or settings.model_name
    kwargs: dict = {}

    # Qwen thinking mode conflicts with tool_choice=required —— 必须关闭。
    # 关闭方式取决于走哪个 API：
    #   Responses API      → reasoning.effort=none（OpenRouter 用法），
    #                        非 ChatOpenAI 顶层参数，走 model_kwargs 透传
    #   Chat Completions   → extra_body.chat_template_kwargs.enable_thinking=false
    #                        （vLLM 部署 qwen3 的原生参数；extra_body 是
    #                         ChatOpenAI 顶层参数，直接传，不放 model_kwargs）
    if "qwen" in model_name.lower():
        if settings.use_responses_api:
            kwargs["model_kwargs"] = {"reasoning": {"effort": "none"}}
        else:
            kwargs["extra_body"] = {
                "chat_template_kwargs": {"enable_thinking": False}
            }

    # 显式配置的 llm_kwargs 优先级更高；对 Qwen 可覆盖上面的默认值，对其他模型也可直接透传额外参数。
    if settings.llm_kwargs:
        kwargs.pop("model_kwargs", None)
        kwargs.pop("extra_body", None)
        kwargs.update(json.loads(settings.llm_kwargs))

    return ChatOpenAI(
        model=model_name,
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        timeout=timeout if timeout is not None else settings.model_timeout,
        temperature=0,
        top_p=1.0,
        max_retries=max_retries,
        # 显式选择 API：默认走 Chat Completions —— vLLM 的 Responses API
        # 不接受历史里的纯文本 assistant 消息，多轮对话会报 400。
        use_responses_api=settings.use_responses_api,
        **kwargs,
    )
