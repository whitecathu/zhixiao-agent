/**
 * Axios 封装
 * - 请求拦截器：注入 Authorization、X-Space-Id、X-Trace-Id、参数格式化
 * - 响应拦截器：统一处理错误码、access token 过期无感刷新、数据脱敏
 */
import axios, { AxiosError, AxiosInstance, InternalAxiosRequestConfig } from "axios";
import { ElMessage } from "element-plus";

import type { ApiResponse, TokenOut } from "@/types";
import { getAuthToken, getRefreshToken, setTokens, clearTokens, getSpaceId } from "./auth";
import { ErrorCode } from "./errorCodes";

const baseURL = (import.meta.env.VITE_API_PREFIX || "/api/v1") as string;

const instance: AxiosInstance = axios.create({
  baseURL,
  timeout: Number(import.meta.env.VITE_REQUEST_TIMEOUT) || 30000,
});

let refreshing: Promise<string> | null = null;
let pending: Array<(token: string) => void> = [];

// ===== 请求拦截 =====
instance.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = getAuthToken();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  const spaceId = getSpaceId();
  if (spaceId) config.headers["X-Space-Id"] = String(spaceId);
  config.headers["X-Trace-Id"] = Math.random().toString(36).slice(2, 18);
  return config;
});

// ===== 响应拦截 =====
instance.interceptors.response.use(
  (resp) => {
    const body = resp.data as ApiResponse;
    if (body.code === 0) return resp;
    // 业务错误统一拦
    handleBusinessError(body);
    return Promise.reject(body);
  },
  async (err: AxiosError<ApiResponse>) => {
    const status = err.response?.status;
    const body = err.response?.data;
    if (status === 401 && body?.code === ErrorCode.AUTH_TOKEN_EXPIRED) {
      // 无感刷新
      try {
        const newToken = await ensureRefresh();
        if (newToken && err.config) {
          err.config.headers.Authorization = `Bearer ${newToken}`;
          return instance(err.config);
        }
      } catch {
        redirectToLogin();
      }
    }
    if (body) {
      handleBusinessError(body);
      return Promise.reject(body);
    }
    ElMessage.error(err.message || "网络异常");
    return Promise.reject(err);
  },
);

function handleBusinessError(body: ApiResponse) {
  ElMessage.error(body.message || "请求失败");
}

function redirectToLogin() {
  clearTokens();
  if (location.pathname !== "/login") location.href = "/login";
}

async function ensureRefresh(): Promise<string> {
  if (refreshing) return new Promise<string>((resolve) => pending.push(resolve));
  refreshing = (async () => {
    const refreshToken = getRefreshToken();
    if (!refreshToken) throw new Error("no refresh token");
    const resp = await axios.post<ApiResponse<TokenOut>>(
      "/api/v1/auth/refresh",
      { refresh_token: refreshToken },
    );
    const data = resp.data.data;
    setTokens(data.access_token, data.refresh_token);
    return data.access_token;
  })();
  try {
    const t = await refreshing;
    pending.forEach((r) => r(t));
    pending = [];
    return t;
  } catch (e) {
    pending.forEach(() => redirectToLogin());
    pending = [];
    redirectToLogin();
    throw e;
  } finally {
    refreshing = null;
  }
}

export default instance;

// 通用请求方法
export async function request<T = unknown>(config: Parameters<AxiosInstance["request"]>[0]): Promise<T> {
  const resp = await instance.request<ApiResponse<T>>(config);
  return resp.data.data;
}
