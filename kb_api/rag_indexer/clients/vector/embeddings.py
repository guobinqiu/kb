from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextvars import copy_context

from kb_api.rag_indexer.common.deadline import check_deadline


def embed_documents(
    dense: Callable[[], list[list[float]]],
    sparse: Callable[[], list[dict[int, float]]] | None,
) -> tuple[list[list[float]], list[dict[int, float]] | None]:
    check_deadline()
    if sparse is None:
        vectors = dense()
        check_deadline()
        return vectors, None

    # Each worker needs its own copy of the request ID, scope and deadline.
    with ThreadPoolExecutor(max_workers=2) as executor:
        dense_future = executor.submit(copy_context().run, dense)
        sparse_future = executor.submit(copy_context().run, sparse)
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
