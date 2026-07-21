/**
 * 与后端 error_codes.py 对应的关键码 - 用于 token 过期等无感刷新判断
 */
export const ErrorCode = {
  AUTH_TOKEN_EXPIRED: 100003,
  AUTH_TOKEN_INVALID: 100002,
  AUTH_TOKEN_MISSING: 100001,
  AUTH_PERMISSION_DENIED: 100008,
} as const;