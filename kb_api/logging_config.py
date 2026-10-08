import logging
from urllib.parse import urlsplit


class HealthCheckAccessFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if record.name != "uvicorn.access" or not isinstance(record.args, tuple) or len(record.args) < 3:
            return True
        return urlsplit(str(record.args[2])).path != "/health"


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, HealthCheckAccessFilter) for item in access_logger.filters):
        access_logger.addFilter(HealthCheckAccessFilter())


def log_request_error(
    logger: logging.Logger,
    *,
    method: str,
    path: str,
    status_code: int,
    trace_id: str,
    error: str,
    level: int,
) -> None:
    logger.log(
        level,
        "Request failed: method=%s path=%s status=%s trace_id=%s error=%s",
        method,
        path,
        status_code,
        trace_id,
        error,
        extra={
            "trace_id": trace_id,
            "method": method,
            "path": path,
            "status": status_code,
        },
    )
