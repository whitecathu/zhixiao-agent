import { request } from "@/utils/request";
import type { TokenOut, User } from "@/types";

export const authApi = {
  register: (data: { username: string; email: string; password: string; nickname?: string }) =>
    request<User>({ method: "POST", url: "/auth/register", data }),
  login: (data: { username: string; password: string }) =>
    request<TokenOut>({ method: "POST", url: "/auth/login", data }),
  refresh: (refresh_token: string) =>
    request<TokenOut>({ method: "POST", url: "/auth/refresh", data: { refresh_token } }),
  logout: (refresh_token: string) =>
    request({ method: "POST", url: "/auth/logout", data: { refresh_token } }),
  changePassword: (data: { old_password: string; new_password: string }) =>
    request({ method: "PUT", url: "/auth/password", data }),
  me: () => request<User>({ method: "GET", url: "/auth/me" }),
};