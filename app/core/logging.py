import logging
import re
import sys
import time
import uuid
from contextvars import ContextVar

from fastapi import Request


__all__ = ["setup_logging", "request_logging_middleware", "current_request_id", "SafeDiagnosticFilter"]


current_request_id: ContextVar[str | None] = ContextVar("evia_request_id", default=None)
_SECRET = re.compile(
    r"(?i)(?:postgres(?:ql)?://[^\s'\"]+|bearer\s+[^\s'\"]+|"
    r"(?:api[_-]?key|password|token|secret)\s*[:=]\s*[^\s,'\"]+)"
)


class SafeDiagnosticFilter(logging.Filter):
    """Keep error type and request ID, never raw exception text/tracebacks."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        if isinstance(record.args, tuple):
            record.args = tuple(
                type(value).__name__ if isinstance(value, BaseException) else value
                for value in record.args
            )
        elif isinstance(record.args, dict):
            record.args = {
                key: type(value).__name__ if isinstance(value, BaseException) else value
                for key, value in record.args.items()
            }
        record.msg = _SECRET.sub("[redacted]", record.getMessage())
        record.args = ()
        return True


def setup_logging() -> None:
    """
    Настраивает логгер
    :return:
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(SafeDiagnosticFilter())
    logging.basicConfig(
        level=logging.INFO,
        format=(
            "%(asctime)s | %(levelname)-8s | "
            "%(name)s | %(message)s"
        ),
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[handler],
        force=True,
    )


logger = logging.getLogger(__name__)


async def request_logging_middleware(
    request: Request,
    call_next,
):
    """
    Лог для обработки подключения к серверу.
    Используется непосредственно ``FastApi``

    :param request: ``Request`` от ``FastApi``
    :param call_next: Что продолжить выполнять
    :return:
    """
    request_id = uuid.uuid4().hex
    token = current_request_id.set(request_id)
    request.state.request_id = request_id
    start_time = time.perf_counter()

    try:
        try:
            response = await call_next(request)
        except Exception as exc:
            logger.error(
                "Request failed | id=%s method=%s path=%s duration=%.3fs error_type=%s",
                request_id, request.method, request.url.path,
                time.perf_counter() - start_time, type(exc).__name__,
            )
            raise

        response.headers["X-Request-ID"] = request_id
        logger.info(
            "Request completed | id=%s method=%s path=%s status=%s duration=%.3fs",
            request_id, request.method, request.url.path, response.status_code,
            time.perf_counter() - start_time,
        )
        return response
    finally:
        current_request_id.reset(token)
