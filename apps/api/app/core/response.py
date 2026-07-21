"""app/core/response.py
统一响应体 - 全系统所有接口返回统一 JSON 结构
{
  "code": 0,           # 0 表示成功，非 0 为 ErrorCode
  "message": "ok",
  "data": <any>,
  "trace_id": "..."
}
"""

from typing import Any, Generic, Optional, TypeVar
from pydantic import BaseModel, Field

from app.core.error_codes import ErrorCode, msg

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    code: int = ErrorCode.OK
    message: str = "ok"
    data: Optional[T] = None
    trace_id: Optional[str] = None

    @classmethod
    def success(cls, data: Any = None, trace_id: Optional[str] = None) -> "ApiResponse":
        return cls(code=ErrorCode.OK, message="ok", data=data, trace_id=trace_id)

    @classmethod
    def fail(
        cls,
        code: ErrorCode = ErrorCode.SYSTEM_ERROR,
        message: Optional[str] = None,
        data: Any = None,
        trace_id: Optional[str] = None,
    ) -> "ApiResponse":
        return cls(code=int(code), message=message or msg(code), data=data, trace_id=trace_id)


class PageData(BaseModel):
    """通用分页响应数据"""

    items: list = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20


class PageResponse(ApiResponse[PageData]):
    data: PageData

    @classmethod
    def of(
        cls, items: list, total: int, page: int, page_size: int, trace_id: Optional[str] = None
    ) -> "PageResponse":
        return cls(
            code=ErrorCode.OK,
            message="ok",
            data=PageData(items=items, total=total, page=page, page_size=page_size),
            trace_id=trace_id,
        )
