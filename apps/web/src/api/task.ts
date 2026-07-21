import { request } from "@/utils/request";
import type { AgentStep, PermissionMode, TaskItem } from "@/types";

export interface TaskRunCreate {
  repository_id: number;
  title: string;
  prompt: string;
  workflow_id?: number;
  agent_id?: number;
  permission_mode?: PermissionMode;
}

export const taskApi = {
  create: (data: TaskRunCreate) =>
    request<TaskItem>({ method: "POST", url: "/task-runs", data }),
  get: (id: number) =>
    request<TaskItem>({ method: "GET", url: `/task-runs/${id}` }),
  list: () =>
    request<TaskItem[]>({ method: "GET", url: "/task-runs" }),
  control: (id: number, action: "interrupt" | "resume") =>
    request<TaskItem>({ method: "POST", url: `/task-runs/${id}/${action}` }),
  log: (id: number) =>
    request<AgentStep[]>({ method: "GET", url: `/task-runs/${id}/steps` }),
};
