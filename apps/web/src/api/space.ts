import { request } from "@/utils/request";
import type { Space, SpaceMember } from "@/types";

export const spaceApi = {
  create: (data: { name: string; description?: string }) =>
    request<Space>({ method: "POST", url: "/spaces", data }),
  mine: () => request<Space[]>({ method: "GET", url: "/spaces/mine" }),
  update: (id: number, data: Partial<{ name: string; description: string }>) =>
    request<Space>({ method: "PUT", url: `/spaces/${id}`, data }),
  addMember: (id: number, data: { user_id: number; role: string }) =>
    request<SpaceMember>({ method: "POST", url: `/spaces/${id}/members`, data }),
  listMembers: (id: number) =>
    request<SpaceMember[]>({ method: "GET", url: `/spaces/${id}/members` }),
  removeMember: (id: number, memberUserId: number) =>
    request({ method: "DELETE", url: `/spaces/${id}/members/${memberUserId}` }),
};