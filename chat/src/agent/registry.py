_graphs: dict = {}
_checkpointer = None


def set_checkpointer(cp):
    global _checkpointer
    _checkpointer = cp


def get_checkpointer():
    if _checkpointer is None:
        raise RuntimeError("Checkpointer 未初始化")
    return _checkpointer


def register_graph(name: str, graph):
    _graphs[name] = graph


def get_graph(name: str):
    if name not in _graphs:
        raise RuntimeError(f"Graph '{name}' 未注册")
    return _graphs[name]


def registered_names() -> list[str]:
    return list(_graphs.keys())
