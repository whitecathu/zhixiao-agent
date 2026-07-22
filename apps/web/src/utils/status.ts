import type { TaskStatus } from "@/types";

const TASK_STATUS_LABEL: Record<TaskStatus, string> = {
  awaiting_approval: "待审批",
  queued: "排队中",
  running: "执行中",
  succeeded: "已完成",
  failed: "失败",
  interrupted: "已中断",
  cancelled: "已取消",
};

const TASK_STATUS_TAG: Record<TaskStatus, "success" | "warning" | "danger" | "info" | "primary"> = {
  awaiting_approval: "warning",
  queued: "info",
  running: "warning",
  succeeded: "success",
  failed: "danger",
  interrupted: "info",
  cancelled: "info",
};

export function taskStatusText(status?: TaskStatus | string): string {
  if (!status) return "未知";
  return TASK_STATUS_LABEL[status as TaskStatus] ?? status;
}

export function taskStatusTag(status?: TaskStatus | string) {
  if (!status) return "info" as const;
  return TASK_STATUS_TAG[status as TaskStatus] ?? ("info" as const);
}
