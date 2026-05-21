import logging
import sys
import warnings
from types import FrameType
from typing import Any, Optional, Union

from loguru import logger


class InterceptHandler(logging.Handler):
    """
    Intercept standard logging messages and redirect them to Loguru.
    """

    def emit(self, record: logging.LogRecord) -> None:
        # Get corresponding Loguru level if it exists
        level: Union[str, int]
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Find caller from where the logging call originated
        frame: Optional[FrameType] = sys._getframe(6)
        depth = 6
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def redirect_warnings(
    message: Union[Warning, str],
    category: type[Warning],
    filename: str,
    lineno: int,
    file: Optional[Any] = None,
    line: Optional[Any] = None,
) -> None:
    """
    Redirect Python warnings to loguru.
    """
    logger.opt(depth=2).warning(f"{category.__name__}: {message} ({filename}:{lineno})")


def setup_interception() -> None:
    """
    Configure standard logging and warnings to use Loguru.
    """
    # 1. Redirect standard logging via root handler
    logging.basicConfig(handlers=[InterceptHandler()], level=logging.DEBUG, force=True)

    # 2. Reconfigure existing loggers to ensure they propagate to root
    for name in logging.root.manager.loggerDict:
        lgr = logging.getLogger(name)
        lgr.handlers = []
        lgr.propagate = True

    # 3. Redirect warnings
    warnings.showwarning = redirect_warnings

    # 4. Standard Library / Third-party overrides
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("datasets").setLevel(logging.WARNING)
    logging.getLogger("filelock").setLevel(logging.WARNING)
