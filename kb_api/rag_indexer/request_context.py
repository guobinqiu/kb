from contextvars import ContextVar
from uuid import uuid4


_request_trace_id: ContextVar[str | None] = ContextVar("request_trace_id", default=None)


def get_trace_id() -> str:
    return _request_trace_id.get() or uuid4().hex


class RequestIdMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        state = scope.setdefault("state", {})
        trace_id = state.setdefault("trace_id", uuid4().hex)
        token = _request_trace_id.set(trace_id)

        async def send_response(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"x-trace-id", trace_id.encode()))
                if state.get("traceparent"):
                    headers.append((b"traceparent", state["traceparent"].encode()))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_response)
        finally:
            _request_trace_id.reset(token)


def install_request_id_middleware(app, *, service_name: str) -> None:
    app.state.service_name = service_name
    app.add_middleware(RequestIdMiddleware)
