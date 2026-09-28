from fastapi import HTTPException


def health():
    return {"status": "ok"}


def ready(state):
    if not state.ready:
        raise HTTPException(503, "search is not initialized")
    components = []
    components.extend((
        ("parser", state.parser_client),
        ("inference", state.inference_client),
        ("vector", state.vector_client),
    ))
    for name, component in components:
        if not _component_ready(component):
            raise HTTPException(503, f"{name} is not ready")
    return {"status": "ready"}


def _component_ready(component) -> bool:
    ping = getattr(component, "ping", None)
    if callable(ping):
        return bool(ping())
    return bool(getattr(component, "ready", False))
