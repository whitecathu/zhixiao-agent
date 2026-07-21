"""app/core/logging.py
基于 loguru 的统一日志配置 - 控制台 + 文件轮转 + 链路追踪 trace_id 注入
"""

import logging
import sys
from loguru import logger

from app.core.config import settings


class InterceptHandler(logging.Handler):
    """让标准 logging 转发到 loguru，便于第三方库（如 uvicorn）日志纳入统一管道"""

    def emit(self, record):
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        frame, depth = logging.currentframe(), 2
        while frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def setup_logging() -> None:
    """在应用启动时调用一次"""
    logger.remove()
    fmt = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "{extra[trace_id]} | {message}"
    )

    logger.configure(extra={"trace_id": "-"})

    logger.add(sys.stdout, format=fmt, level=settings.LOG_LEVEL, enqueue=True)
    logger.add(
        "logs/app_{time:YYYYMMDD}.log",
        rotation="00:00",
        retention="14 days",
        level=settings.LOG_LEVEL,
        format=fmt,
        enqueue=True,
        encoding="utf-8",
    )
    # 第三方库日志 -> loguru
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi", "sqlalchemy"):
        logging.getLogger(name).handlers = [InterceptHandler()]
        logging.getLogger(name).propagate = False


def get_logger():
    return logger
