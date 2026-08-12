import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { invocationToTest, invocationsToTerminal, isTestInvocation, useTaskStore } from "./task";
import type { ToolInvocation } from "@/types";

vi.mock("@/api/task", () => ({
  taskApi: { get: vi.fn(), log: vi.fn(), create: vi.fn(), control: vi.fn() },
}));

describe("task store event projection", () => {
  beforeEach(() => setActivePinia(createPinia()));

  it("projects output, terminal and run state while deduplicating event ids", () => {
    const store = useTaskStore();
    store.currentTask = {
      id: 1, space_id: 1, user_id: 1, repository_id: 2, title: "run",
      prompt: "test the complete execution", status: "running", permission_mode: "edit",
      created_at: "2026-01-01", updated_at: "2026-01-01",
    };
    store.handleSSE({ id: "1-0", event: "output", data: { subtask_id: "api", delta: "hello" } });
    store.handleSSE({ id: "1-0", event: "output", data: { subtask_id: "api", delta: "duplicate" } });
    store.handleSSE({ id: "2-0", event: "terminal", data: { line: "pytest -q" } });
    store.handleSSE({ id: "3-0", event: "run", data: { status: "succeeded" } });

    expect(store.streamedChunks.api).toBe("hello");
    expect(store.terminalLines).toEqual(["pytest -q"]);
    expect(store.currentTask?.status).toBe("succeeded");
    expect(store.sseEvents).toHaveLength(3);
    expect(store.lastEventId).toBe("3-0");
  });

  it("resets all execution projections", () => {
    const store = useTaskStore();
    store.handleSSE({ id: "1", event: "terminal", data: { line: "npm test" } });
    store.diff = "patch";
    store.reset();
    expect(store.terminalLines).toEqual([]);
    expect(store.sseEvents).toEqual([]);
    expect(store.diff).toBe("");
    expect(store.lastEventId).toBeNull();
  });

  it("projects persisted run_tests and terminal tool invocations", () => {
    const invocation: ToolInvocation = {
      id: 7, task_run_id: 1, run_step_id: 2, agent_name: "tester", tool_name: "run_tests",
      input: { command: "pytest -q" }, status: "succeeded", duration_ms: 125,
      result: { status: "succeeded", summary: "31 passed", next_actions: [], artifacts: [] },
      created_at: "2026-01-01", updated_at: "2026-01-01",
    };
    expect(isTestInvocation(invocation)).toBe(true);
    expect(invocationToTest(invocation)).toEqual({
      id: "7", command: "pytest -q", status: "passed", duration_ms: 125, summary: "31 passed",
    });
    expect(invocationsToTerminal([invocation])).toEqual(["$ pytest -q", "31 passed"]);
  });
});
