from typing import Any

def get_config(state, _):
    return config_payload(state)


def config_payload(state) -> dict[str, Any]:
    cfg = {
        "config_name": state.config_name,
    }
    cfg["capabilities"] = capabilities(state)
    cfg["services"] = services_config(state)
    cfg["available_components"] = state.config.available_components
    return cfg


def capabilities(state) -> dict[str, bool]:
    vector = state.vector_client
    return {
        "dense_vector": _supports(vector, "supports_dense_vector"),
        "sparse_vector": _supports(vector, "supports_sparse_vector"),
        "app_management": False,
        "file_records": False,
        "file_upload": bool(state.config.storage.endpoint_url),
    }


def _supports(component: Any, method_name: str, *args) -> bool:
    method = getattr(component, method_name, None)
    if not callable(method):
        return False
    return bool(method(*args))


def services_config(state) -> dict[str, dict[str, Any]]:
    services = state.config.services
    result = {
        "vector": _service_config(services.vector),
    }
    return result


def _service_config(service: Any) -> dict[str, Any]:
    return {
        key: value
        for key, value in {
            "base_url": service.base_url,
            "timeout": service.timeout,
        }.items()
        if value is not None
    }


def profile(state) -> dict[str, Any]:
    return {
        "config_name": state.config_name,
        "services": services_config(state),
    }
