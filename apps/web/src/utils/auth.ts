/**
 * 浏览器存储工具 - access / refresh token + 当前空间 ID
 */
const ACCESS_KEY = import.meta.env.VITE_TOKEN_KEY || "zhixiao_access_token";
const REFRESH_KEY = import.meta.env.VITE_REFRESH_KEY || "zhixiao_refresh_token";
const SPACE_KEY = "zhixiao_space_id";

export function getAuthToken(): string | null {
  return localStorage.getItem(ACCESS_KEY);
}
export function getRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_KEY);
}
export function setTokens(access: string, refresh: string): void {
  localStorage.setItem(ACCESS_KEY, access);
  localStorage.setItem(REFRESH_KEY, refresh);
}
export function clearTokens(): void {
  localStorage.removeItem(ACCESS_KEY);
  localStorage.removeItem(REFRESH_KEY);
}
export function getSpaceId(): number | null {
  const s = localStorage.getItem(SPACE_KEY);
  return s ? Number(s) : null;
}
export function setSpaceId(id: number): void {
  localStorage.setItem(SPACE_KEY, String(id));
}
export function clearSpaceId(): void {
  localStorage.removeItem(SPACE_KEY);
}