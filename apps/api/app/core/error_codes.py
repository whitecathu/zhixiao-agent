"""app/core/error_codes.py
全局错误码枚举 - 全系统统一错误码规范
格式: <类别码 2位>-<具体码 4位>
类别: 10 auth(认证)   11 user   12 space   13 task
      14 execution   15 knowledge   16 tool   17 stats   99 system
"""

from enum import IntEnum


class ErrorCode(IntEnum):
    # 系统
    OK = 0
    SYSTEM_ERROR = 990001
    SYSTEM_BUSY = 990002
    SYSTEM_TIMEOUT = 990003
    PARAM_INVALID = 990004
    NOT_FOUND = 990005
    METHOD_NOT_ALLOWED = 990006
    RATE_LIMITED = 990007
    DB_ERROR = 990008
    REDIS_ERROR = 990009

    # 认证 (10xxxx)
    AUTH_TOKEN_MISSING = 100001
    AUTH_TOKEN_INVALID = 100002
    AUTH_TOKEN_EXPIRED = 100003
    AUTH_REFRESH_INVALID = 100004
    AUTH_REFRESH_EXPIRED = 100005
    AUTH_LOGIN_FAIL = 100006
    AUTH_USER_LOCKED = 100007
    AUTH_PERMISSION_DENIED = 100008
    AUTH_USER_NOT_FOUND = 100009

    # 用户 (11xxxx)
    USER_EXISTS = 110001
    USER_PASSWORD_WEAK = 110002

    # 空间 (12xxxx)
    SPACE_NOT_FOUND = 120001
    SPACE_MEMBER_EXISTS = 120002
    SPACE_MEMBER_NOT_FOUND = 120003
    SPACE_QUOTA_EXCEED = 120004

    # 任务 (13xxxx)
    TASK_NOT_FOUND = 130001
    TASK_STATE_INVALID = 130002
    TASK_DUPLICATE = 130003
    TASK_TEMPLATE_NOT_FOUND = 130004

    # 执行 (14xxxx)
    EXECUTION_NOT_RUNNING = 140001
    EXECUTION_INTERRUPT_FAIL = 140002
    EXECUTION_RESUME_FAIL = 140003
    EXECUTION_ENGINE_ERROR = 140004

    # 知识 (15xxxx)
    KNOWLEDGE_NOT_FOUND = 150001
    KNOWLEDGE_VECTOR_PENDING = 150002
    KNOWLEDGE_DUPLICATE = 150003

    # 工具 (16xxxx)
    TOOL_NOT_FOUND = 160001
    TOOL_INVOCATION_FAIL = 160002


ERROR_MESSAGES = {
    ErrorCode.OK: "ok",
    ErrorCode.SYSTEM_ERROR: "系统内部错误",
    ErrorCode.SYSTEM_BUSY: "系统繁忙",
    ErrorCode.SYSTEM_TIMEOUT: "系统超时",
    ErrorCode.PARAM_INVALID: "参数非法",
    ErrorCode.NOT_FOUND: "资源不存在",
    ErrorCode.METHOD_NOT_ALLOWED: "方法不允许",
    ErrorCode.RATE_LIMITED: "请求过于频繁",
    ErrorCode.DB_ERROR: "数据库错误",
    ErrorCode.REDIS_ERROR: "缓存错误",
    ErrorCode.AUTH_TOKEN_MISSING: "缺少鉴权令牌",
    ErrorCode.AUTH_TOKEN_INVALID: "令牌无效",
    ErrorCode.AUTH_TOKEN_EXPIRED: "令牌已过期",
    ErrorCode.AUTH_REFRESH_INVALID: "刷新令牌无效",
    ErrorCode.AUTH_REFRESH_EXPIRED: "刷新令牌已过期",
    ErrorCode.AUTH_LOGIN_FAIL: "用户名或密码错误",
    ErrorCode.AUTH_USER_LOCKED: "账号被锁定，请稍后再试",
    ErrorCode.AUTH_PERMISSION_DENIED: "无权限访问",
    ErrorCode.AUTH_USER_NOT_FOUND: "用户不存在",
    ErrorCode.USER_EXISTS: "用户已存在",
    ErrorCode.USER_PASSWORD_WEAK: "密码强度不足",
    ErrorCode.SPACE_NOT_FOUND: "空间不存在",
    ErrorCode.SPACE_MEMBER_EXISTS: "成员已存在",
    ErrorCode.SPACE_MEMBER_NOT_FOUND: "成员不存在",
    ErrorCode.SPACE_QUOTA_EXCEED: "空间配额超出",
    ErrorCode.TASK_NOT_FOUND: "任务不存在",
    ErrorCode.TASK_STATE_INVALID: "任务状态不允许此操作",
    ErrorCode.TASK_DUPLICATE: "任务创建重复",
    ErrorCode.TASK_TEMPLATE_NOT_FOUND: "模板不存在",
    ErrorCode.EXECUTION_NOT_RUNNING: "任务未运行",
    ErrorCode.EXECUTION_INTERRUPT_FAIL: "任务中断失败",
    ErrorCode.EXECUTION_RESUME_FAIL: "任务恢复失败",
    ErrorCode.EXECUTION_ENGINE_ERROR: "AI 引擎错误",
    ErrorCode.KNOWLEDGE_NOT_FOUND: "知识不存在",
    ErrorCode.KNOWLEDGE_VECTOR_PENDING: "向量入库待处理",
    ErrorCode.KNOWLEDGE_DUPLICATE: "知识条目重复",
    ErrorCode.TOOL_NOT_FOUND: "工具不存在",
    ErrorCode.TOOL_INVOCATION_FAIL: "工具调用失败",
}


def msg(code: ErrorCode) -> str:
    return ERROR_MESSAGES.get(code, "未知错误")
