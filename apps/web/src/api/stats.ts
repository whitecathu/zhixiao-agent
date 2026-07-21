import { request } from "@/utils/request";
import type { AgentStat, SpaceOverview } from "@/types";

export const statsApi = {
  overview: () => request<SpaceOverview>({ method: "GET", url: "/stats/overview" }),
  agents: () => request<AgentStat[]>({ method: "GET", url: "/stats/agents" }),
  recentTasks: () =>
    request<{ id: number; title: string; status: string; created_at: string | null }[]>(
      { method: "GET", url: "/stats/recent-tasks" },
    ),
  replay: (taskId: number) =>
    request<{ step_index: number; agent_name: string; status: string;
             tools_used?: string[] | null; duration_ms: number;
             started_at: string | null; finished_at: string | null }[]>(
      { method: "GET", url: `/stats/tasks/${taskId}/replay` },
    ),
};