"""app/core/exceptions.py
全局异常体系 - 业务异常 + 异常处理器注册
"""

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.error_codes import ErrorCode
from app.core.response import ApiResponse


class BizException(Exception):
    """业务异常 - 携带 ErrorCode"""

    def __init__(
        self,
        code: ErrorCode = ErrorCode.SYSTEM_ERROR,
        message: str | None = None,
        data: Any = None,
        http_status: int = 200,
    ):
        self.code = code
        self.message = message
        self.data = data
        self.http_status = http_status
        super().__init__(message or code.name)


def register_exception_handlers(app: FastAPI) -> None:
    """注册全局异常处理器 - 给 FastAPI 统一兜底"""

    @app.exception_handler(BizException)
    async def _biz_handler(request: Request, exc: BizException):
        trace_id = getattr(request.state, "trace_id", None)
        return JSONResponse(
            status_code=exc.http_status,
            content=ApiResponse.fail(
                code=exc.code, message=exc.message, data=exc.data, trace_id=trace_id
            ).model_dump(),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(request: Request, exc: RequestValidationError):
        trace_id = getattr(request.state, "trace_id", None)
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=ApiResponse.fail(
                code=ErrorCode.PARAM_INVALID,
                message="参数校验失败",
                data=[
                    {key: value for key, value in error.items() if key != "ctx"}
                    for error in exc.errors()
                ],
                trace_id=trace_id,
            ).model_dump(),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_handler(request: Request, exc: StarletteHTTPException):
        trace_id = getattr(request.state, "trace_id", None)
        code_map = {
            401: ErrorCode.AUTH_TOKEN_MISSING,
            403: ErrorCode.AUTH_PERMISSION_DENIED,
            404: ErrorCode.NOT_FOUND,
            405: ErrorCode.METHOD_NOT_ALLOWED,
            429: ErrorCode.RATE_LIMITED,
        }
        code = code_map.get(exc.status_code, ErrorCode.SYSTEM_ERROR)
        return JSONResponse(
            status_code=exc.status_code,
            content=ApiResponse.fail(code=code, trace_id=trace_id).model_dump(),
        )

    @app.exception_handler(Exception)
    async def _unk_handler(request: Request, exc: Exception):
        # 详见 logging.py 中 logger.error 全链路记录
        trace_id = getattr(request.state, "trace_id", None)
        return JSONResponse(
            status_code=500,
            content=ApiResponse.fail(
                code=ErrorCode.SYSTEM_ERROR, message="系统内部错误", trace_id=trace_id
            ).model_dump(),
        )
