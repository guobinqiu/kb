import logging

from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from kb_api.rag_indexer.core.index import create_file_id
from kb_api.rag_indexer.core.index.errors import index_error_detail
from kb_api.rag_indexer.common.tracing import get_trace_id
from kb_api.rag_indexer.common.upstream import UpstreamServiceError


logger = logging.getLogger("rag_indexer")


def _is_index_request(request):
    return request.method == "POST" and request.url.path in {"/api/rag/files", "/api/v1/rag/files"}


def _response(exc, status_code):
    file_id = create_file_id()
    error = UpstreamServiceError(service="rag", error=str(exc), retryable=status_code == 503, status_code=status_code)
    logger.error("Index request rejected", exc_info=(type(exc), exc, exc.__traceback__), extra={
        "trace_id": get_trace_id(), "file_id": file_id, "retryable": error.retryable,
    })
    return JSONResponse(status_code=status_code, content=index_error_detail(error, file_id))


async def _http_error(request, exc):
    if _is_index_request(request):
        return _response(exc, exc.status_code)
    return await http_exception_handler(request, exc)


async def _validation_error(request, exc):
    if _is_index_request(request):
        return _response(exc, 422)
    return await request_validation_exception_handler(request, exc)


def install_index_error_handlers(app):
    app.add_exception_handler(HTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
