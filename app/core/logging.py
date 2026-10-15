import logging
import sys
import time
import uuid

from fastapi import Request


def setup_logging() -> None:
    """
    Настраивает логгер
    :return:
    """
    logging.basicConfig(
        level=logging.INFO,
        format=(
            "%(asctime)s | %(levelname)-8s | "
            "%(name)s | %(message)s"
        ),
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
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
    request_id = str(uuid.uuid4())[:8]
    start_time = time.perf_counter()

    try:
        response = await call_next(request)
    except Exception:
        duration = time.perf_counter() - start_time

        logger.exception(
            "Request failed | id=%s method=%s path=%s duration=%.3fs",
            request_id,
            request.method,
            request.url.path,
            duration,
        )
        raise

    duration = time.perf_counter() - start_time

    response.headers["X-Request-ID"] = request_id

    logger.info(
        "Request completed | id=%s method=%s path=%s "
        "status=%s duration=%.3fs",
        request_id,
        request.method,
        request.url.path,
        response.status_code,
        duration,
    )

    return response
