import { defineStore } from "pinia";
import { ref } from "vue";

import { taskApi } from "@/api/task";
import type { AgentStep, Approval, Artifact, TaskItem, SSEPayload, TestResult, ToolInvocation } from "@/types";

export function invocationToTest(item: ToolInvocation): TestResult {
  const command = typeof item.input?.command === "string" ? item.input.command : item.tool_name;
  const status = item.result.status === "succeeded" ? "passed" :
    item.result.status === "failed" ? "failed" : "skipped";
  return { id: String(item.id), command, status, duration_ms: item.duration_ms, summary: item.result.summary };
}

const TERMINAL_TOOLS = new Set(["terminal", "run_tests", "test"]);

export function isTestInvocation(item: ToolInvocation): boolean {
  return item.tool_name === "run_tests" || item.tool_name === "test";
}

export function invocationsToTerminal(items: ToolInvocation[]): string[] {
  return items.filter((item) => TERMINAL_TOOLS.has(item.tool_name))
    .flatMap((item) => {
      const command = typeof item.input?.command === "string" ? `$ ${item.input.command}` : `$ ${item.tool_name}`;
      return [command, item.result.summary, item.result.error_root_cause].filter((line): line is string => Boolean(line));
    });
}

export const useTaskStore = defineStore("task", () => {
  const currentTask = ref<TaskItem | null>(null);
  const timeline = ref<AgentStep[]>([]);
  const streamedChunks = ref<Record<string, string>>({});   // subtask_id -> 文本
  const sseEvents = ref<SSEPayload[]>([]);
  const approvals = ref<Approval[]>([]);
  const artifacts = ref<Artifact[]>([]);
  const tests = ref<TestResult[]>([]);
  const diff = ref("");
  const terminalLines = ref<string[]>([]);
  const lastEventId = ref<string | null>(null);

  function reset() {
    currentTask.value = null;
    timeline.value = [];
    streamedChunks.value = {};
    sseEvents.value = [];
    approvals.value = [];
    artifacts.value = [];
    tests.value = [];
    diff.value = "";
    terminalLines.value = [];
    lastEventId.value = null;
  }

  async function load(taskId: number) {
    currentTask.value = await taskApi.get(taskId);
    timeline.value = await taskApi.log(taskId);
  }

  async function create(payload: {
    title: string; prompt: string; repository_id: number;
    workflow_id?: number; agent_id?: number;
    permission_mode?: "read_only" | "edit" | "execute" | "full";
  }) {
    return await taskApi.create(payload);
  }

  async function interrupt(id: number) { await taskApi.control(id, "interrupt"); }
  async function resume(id: number) { await taskApi.control(id, "resume"); }

  function handleSSE(payload: SSEPayload) {
    if (payload.id && payload.id === lastEventId.value) return;
    if (payload.id) lastEventId.value = payload.id;
    sseEvents.value.push(payload);
    if (sseEvents.value.length > 500) sseEvents.value.splice(0, sseEvents.value.length - 500);
    if (payload.event === "token" || payload.event === "output") {
      const sub = (payload.data as { subtask_id?: string }).subtask_id || "default";
      const chunk = (payload.data as { delta?: string; content?: string }).delta ||
        (payload.data as { content?: string }).content || "";
      streamedChunks.value[sub] = (streamedChunks.value[sub] || "") + chunk;
    }
    if (payload.event === "terminal") {
      const line = String(payload.data.line || payload.data.content || "");
      if (line) terminalLines.value.push(line);
      if (terminalLines.value.length > 1000) terminalLines.value.splice(0, 200);
    }
    if (payload.event === "run" || payload.event === "task_end") {
      const status = payload.data.status as TaskItem["status"] | undefined;
      if (status && currentTask.value) currentTask.value.status = status;
    }
  }

  async function loadRunDetails(taskId: number) {
    const { runApi } = await import("@/api/agent");
    const results = await Promise.allSettled([
      runApi.approvals(taskId), runApi.artifacts(taskId), runApi.toolInvocations(taskId), runApi.diff(taskId),
    ]);
    if (results[0].status === "fulfilled") approvals.value = results[0].value;
    if (results[1].status === "fulfilled") artifacts.value = results[1].value;
    if (results[2].status === "fulfilled") {
      tests.value = results[2].value.filter(isTestInvocation).map(invocationToTest);
      terminalLines.value = invocationsToTerminal(results[2].value);
    }
    if (results[3].status === "fulfilled") diff.value = results[3].value.unified_diff;
  }

  async function decideApproval(approvalId: number, decision: "approved" | "rejected") {
    const { runApi } = await import("@/api/agent");
    const updated = await runApi.decide(approvalId, decision);
    approvals.value = approvals.value.map((item) => item.id === updated.id ? updated : item);
  }

  async function requestApproval(
    taskId: number,
    operation: "destructive_command" | "git_publish" | "mcp" | "sub_agent" | "network_tools",
  ) {
    const { runApi } = await import("@/api/agent");
    const created = await runApi.requestApproval(taskId, operation);
    approvals.value.push(created);
    return created;
  }

  async function getReplay(taskId: number) {
    return await (await import("@/api/stats")).statsApi.replay(taskId);
  }

  return {
    currentTask, timeline, streamedChunks, sseEvents, approvals, artifacts, tests, diff,
    terminalLines, lastEventId,
    reset, load, create, interrupt, resume, handleSSE, loadRunDetails, decideApproval,
    requestApproval, getReplay,
  };
});
