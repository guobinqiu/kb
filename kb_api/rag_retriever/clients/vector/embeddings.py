from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextvars import copy_context

from kb_api.rag_retriever.common.deadline import check_deadline


def _embed(operation, kind: str, model: str | None):
    return operation()


def embed_documents(
    dense: Callable[[], list[list[float]]],
    sparse: Callable[[], list[dict[int, float]]] | None,
    *,
    dense_model: str | None = None,
    sparse_model: str | None = None,
) -> tuple[list[list[float]], list[dict[int, float]] | None]:
    check_deadline()
    if sparse is None:
        vectors = _embed(dense, "dense", dense_model)
        check_deadline()
        return vectors, None

    # Each worker needs its own copy of the request's trace, scope and deadline.
    with ThreadPoolExecutor(max_workers=2) as executor:
        dense_future = executor.submit(copy_context().run, _embed, dense, "dense", dense_model)
        sparse_future = executor.submit(copy_context().run, _embed, sparse, "sparse", sparse_model)
        futures = (dense_future, sparse_future)
        try:
            for future in as_completed(futures):
                future.result()
                check_deadline()
        except BaseException:
            for future in futures:
                future.cancel()
            raise
    return dense_future.result(), sparse_future.result()
