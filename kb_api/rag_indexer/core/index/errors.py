import logging
import time
from contextlib import contextmanager

import httpx
from fastapi import HTTPException

from kb_api.rag_indexer.common.deadline import check_deadline
from kb_api.rag_indexer.common.tracing import get_trace_id
from kb_api.rag_indexer.common.upstream import UpstreamServiceError, upstream_error


logger = logging.getLogger("rag_indexer")


def index_error_detail(error: UpstreamServiceError, file_id: str) -> dict:
    return {
        "success": False, "error": error.error, "service": error.service, "retryable": error.retryable,
        "file_id": file_id, "traceId": get_trace_id(),
    }


@contextmanager
def index_stage(stage: str, service: str):
    started = time.monotonic()
    failed = False
    try:
        check_deadline()
        yield
        check_deadline()
    except UpstreamServiceError as exc:
        failed = True
        logger.exception("Index stage failed", extra={"stage": stage, "service": service, "trace_id": get_trace_id()})
        raise
    except HTTPException:
        failed = True
        logger.exception("Index stage rejected", extra={"stage": stage, "service": service, "trace_id": get_trace_id()})
        raise
    except Exception as exc:
        if isinstance(exc, httpx.HTTPError):
            error = upstream_error(service, exc)
        else:
            error = UpstreamServiceError(
                service=service, error=str(exc) or None,
                retryable=False, status_code=500,
            )
        failed = True
        logger.exception("Index stage failed", extra={"stage": stage, "service": service, "trace_id": get_trace_id()})
        raise error from exc
    finally:
        logger.info("Index stage", extra={
            "event": "index_stage", "stage": stage, "trace_id": get_trace_id(),
            "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
            "status": "failed" if failed else "success",
        })
