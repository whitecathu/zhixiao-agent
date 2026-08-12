import type { SSEPayload } from "@/types";

export type GraphNodeStatus = "idle" | "waiting" | "running" | "succeeded" | "failed";

export interface ExecutionGraphNode {
  id: string;
  label: string;
  hint: string;
}

export interface ExecutionGraphEdge {
  id: string;
  source: string;
  target: string;
  kind?: "default" | "repair";
}

export interface NodeStatusSnapshot {
  statuses: Record<string, GraphNodeStatus>;
  activeNodeId: string | null;
  detail: string;
}

/** Default LangGraph stages used by AgentRuntime when no custom workflow is bound. */
export const DEFAULT_EXECUTION_NODES: ExecutionGraphNode[] = [
  { id: "intake", label: "接入", hint: "任务分类与路由" },
  { id: "discover", label: "探测", hint: "仓库与项目指令" },
  { id: "plan", label: "计划", hint: "生成执行计划" },
  { id: "awaiting", label: "审批", hint: "等待计划确认" },
  { id: "prepare_workspace", label: "工作区", hint: "隔离 worktree" },
  { id: "execute", label: "执行", hint: "模型与工具循环" },
  { id: "verify", label: "验证", hint: "运行测试" },
  { id: "repair", label: "修复", hint: "失败后回修" },
  { id: "finalize", label: "交付", hint: "Diff 与结果" },
];

export const DEFAULT_EXECUTION_EDGES: ExecutionGraphEdge[] = [
  { id: "e-intake-discover", source: "intake", target: "discover" },
  { id: "e-discover-plan", source: "discover", target: "plan" },
  { id: "e-plan-awaiting", source: "plan", target: "awaiting" },
  { id: "e-awaiting-prepare", source: "awaiting", target: "prepare_workspace" },
  { id: "e-prepare-execute", source: "prepare_workspace", target: "execute" },
  { id: "e-execute-verify", source: "execute", target: "verify" },
  { id: "e-verify-finalize", source: "verify", target: "finalize" },
  { id: "e-verify-repair", source: "verify", target: "repair", kind: "repair" },
  { id: "e-repair-execute", source: "repair", target: "execute", kind: "repair" },
];

const SOURCE_EVENT_TO_NODE: Record<string, string> = {
  run_started: "intake",
  repository_discovered: "discover",
  plan_created: "plan",
  approval_required: "awaiting",
  approval_decided: "awaiting",
  worktree_created: "prepare_workspace",
  worktree_skipped: "prepare_workspace",
  model_turn: "execute",
  tool_result: "execute",
  verification_finished: "verify",
  verification_skipped: "verify",
  repair_started: "repair",
  run_finished: "finalize",
};

const NODE_LABELS = Object.fromEntries(
  DEFAULT_EXECUTION_NODES.map((node) => [node.id, node.label]),
) as Record<string, string>;
const DEFAULT_NODE_IDS = new Set(DEFAULT_EXECUTION_NODES.map((node) => node.id));
const WORKFLOW_ROLE_TO_DEFAULT_NODE: Record<string, string> = {
  planner: "plan",
  explorer: "discover",
  knowledge: "discover",
  implementer: "execute",
  tester: "verify",
  reviewer: "finalize",
};
const WORKFLOW_NODE_ALIASES: Record<string, string> = {
  planning: "plan",
  discovery: "discover",
  prepare: "prepare_workspace",
  workspace: "prepare_workspace",
  implementation: "execute",
  test: "verify",
  testing: "verify",
  review: "finalize",
};

function emptyStatuses(): Record<string, GraphNodeStatus> {
  return Object.fromEntries(DEFAULT_EXECUTION_NODES.map((node) => [node.id, "idle" as GraphNodeStatus]));
}

/** Prefer worker `source_event`; fall back to projected event / content name. */
export function resolveSourceEvent(payload: Pick<SSEPayload, "event" | "data">): string {
  const data = payload.data || {};
  if (typeof data.source_event === "string" && data.source_event) {
    return data.source_event;
  }
  if (payload.event === "output" && typeof data.content === "string" && !data.subtask_id && !data.delta) {
    const content = data.content.trim();
    if (content in SOURCE_EVENT_TO_NODE || content.startsWith("workflow_node_")) {
      return content;
    }
  }
  return payload.event;
}

function resolveNodeId(sourceEvent: string, data: Record<string, unknown>): string | null {
  if (sourceEvent === "workflow_node_started" || sourceEvent === "workflow_node_finished" || sourceEvent === "workflow_node_retry") {
    const nodeId = data.node_id;
    if (typeof nodeId === "string" && nodeId) {
      const roleNode =
        typeof data.role === "string" ? mapWorkflowRoleToDefault(data.role) : null;
      return roleNode ?? mapWorkflowRoleToDefault(nodeId);
    }
  }
  return SOURCE_EVENT_TO_NODE[sourceEvent] ?? null;
}

function mapWorkflowRoleToDefault(roleOrId: string): string | null {
  const normalized = roleOrId
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^workflow_(?:node_)?/, "")
    .replace(/^role_/, "")
    .replace(/^_+|_+$/g, "");
  if (!normalized) return null;
  if (DEFAULT_NODE_IDS.has(normalized)) return normalized;
  if (WORKFLOW_NODE_ALIASES[normalized]) return WORKFLOW_NODE_ALIASES[normalized];

  for (const token of normalized.split("_")) {
    if (WORKFLOW_ROLE_TO_DEFAULT_NODE[token]) {
      return WORKFLOW_ROLE_TO_DEFAULT_NODE[token];
    }
  }
  return null;
}

function completePrevious(statuses: Record<string, GraphNodeStatus>, activeId: string | null, nextId: string) {
  if (activeId && activeId !== nextId && statuses[activeId] === "running") {
    statuses[activeId] = "succeeded";
  }
}

function isFailureEvent(sourceEvent: string, data: Record<string, unknown>): boolean {
  if (sourceEvent === "run_finished") {
    return String(data.status || "") === "failed" || String(data.status || "") === "cancelled";
  }
  if (sourceEvent === "verification_finished") {
    const exit = data.exit_code;
    const status = String(data.status || "");
    if (status === "failed") return true;
    return typeof exit === "number" && exit !== 0;
  }
  if (sourceEvent === "workflow_node_finished") {
    return Boolean(data.failed);
  }
  return false;
}

function detailFor(sourceEvent: string, nodeId: string, data: Record<string, unknown>): string {
  const label = NODE_LABELS[nodeId] || nodeId;
  if (sourceEvent === "approval_required") return `${label} · 等待审批`;
  if (sourceEvent === "tool_result") {
    const tool = typeof data.tool === "string" ? data.tool : "tool";
    const summary = typeof data.summary === "string" ? data.summary : "";
    return summary ? `${label} · ${tool}: ${summary}` : `${label} · ${tool}`;
  }
  if (sourceEvent === "model_turn") {
    const tools = Array.isArray(data.tool_calls) ? data.tool_calls.length : 0;
    return tools ? `${label} · 模型回合（${tools} 个工具）` : `${label} · 模型回合`;
  }
  if (sourceEvent === "repair_started") {
    const round = data.round ?? "?";
    return `${label} · 第 ${round} 轮`;
  }
  if (sourceEvent === "verification_finished") {
    return `${label} · exit ${data.exit_code ?? "?"}`;
  }
  if (sourceEvent === "run_finished") {
    return `${label} · ${String(data.status || "finished")}`;
  }
  return label;
}

/**
 * Project SSE payloads into default-graph node statuses for live visualization.
 * Chronological: each stage event completes the previous running node.
 */
export function deriveExecutionGraph(events: Array<Pick<SSEPayload, "event" | "data">>): NodeStatusSnapshot {
  const statuses = emptyStatuses();
  let activeNodeId: string | null = null;
  let detail = "等待运行事件";

  for (const payload of events) {
    const sourceEvent = resolveSourceEvent(payload);
    const data = payload.data || {};
    const nodeId = resolveNodeId(sourceEvent, data);
    if (!nodeId || !(nodeId in statuses)) continue;

    completePrevious(statuses, activeNodeId, nodeId);

    if (sourceEvent === "approval_required") {
      statuses[nodeId] = "waiting";
      activeNodeId = nodeId;
      detail = detailFor(sourceEvent, nodeId, data);
      continue;
    }

    if (sourceEvent === "approval_decided") {
      statuses[nodeId] = data.approved === false ? "failed" : "succeeded";
      activeNodeId = data.approved === false ? nodeId : null;
      detail = data.approved === false ? `${NODE_LABELS[nodeId]} · 已拒绝` : `${NODE_LABELS[nodeId]} · 已批准`;
      continue;
    }

    if (isFailureEvent(sourceEvent, data)) {
      statuses[nodeId] = "failed";
      activeNodeId = nodeId;
      detail = detailFor(sourceEvent, nodeId, data);
      if (sourceEvent === "run_finished") {
        // keep finalize failed; earlier running nodes already completed
      }
      continue;
    }

    if (
      sourceEvent === "run_finished" ||
      sourceEvent === "approval_decided" ||
      sourceEvent === "workflow_node_finished" ||
      sourceEvent === "worktree_created" ||
      sourceEvent === "worktree_skipped" ||
      sourceEvent === "repository_discovered" ||
      sourceEvent === "plan_created" ||
      sourceEvent === "verification_skipped"
    ) {
      statuses[nodeId] = "succeeded";
      activeNodeId = sourceEvent === "run_finished" ? null : nodeId;
      if (sourceEvent === "run_finished") {
        for (const id of Object.keys(statuses)) {
          if (statuses[id] === "running" || statuses[id] === "waiting") statuses[id] = "succeeded";
        }
        statuses.finalize = "succeeded";
        activeNodeId = null;
      }
      detail = detailFor(sourceEvent, nodeId, data);
      continue;
    }

    // Long-lived stages stay running (execute / verify / repair / intake)
    statuses[nodeId] = "running";
    activeNodeId = nodeId;
    detail = detailFor(sourceEvent, nodeId, data);
  }

  return { statuses, activeNodeId, detail };
}

export function layoutDefaultNodes(
  statuses: Record<string, GraphNodeStatus>,
  activeNodeId: string | null,
): Array<{ id: string; position: { x: number; y: number }; data: ExecutionGraphNode & { status: GraphNodeStatus; active: boolean } }> {
  // Two-row layout: main path on top, repair on the bottom loop.
  const positions: Record<string, { x: number; y: number }> = {
    intake: { x: 0, y: 40 },
    discover: { x: 160, y: 40 },
    plan: { x: 320, y: 40 },
    awaiting: { x: 480, y: 40 },
    prepare_workspace: { x: 640, y: 40 },
    execute: { x: 800, y: 40 },
    verify: { x: 960, y: 40 },
    finalize: { x: 1120, y: 40 },
    repair: { x: 880, y: 180 },
  };
  return DEFAULT_EXECUTION_NODES.map((node) => ({
    id: node.id,
    position: positions[node.id] || { x: 0, y: 0 },
    data: {
      ...node,
      status: statuses[node.id] || "idle",
      active:
        activeNodeId === node.id &&
        (statuses[node.id] === "running" || statuses[node.id] === "waiting"),
    },
  }));
}
