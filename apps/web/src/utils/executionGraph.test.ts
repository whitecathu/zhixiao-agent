import { describe, expect, it } from "vitest";

import {
  deriveExecutionGraph,
  resolveSourceEvent,
} from "./executionGraph";

describe("executionGraph", () => {
  it("resolves source_event from worker projection", () => {
    expect(
      resolveSourceEvent({
        event: "output",
        data: { source_event: "repository_discovered", content: "repository_discovered" },
      }),
    ).toBe("repository_discovered");
    expect(
      resolveSourceEvent({
        event: "tool",
        data: { source_event: "tool_result", tool: "read_file" },
      }),
    ).toBe("tool_result");
  });

  it("walks the default LangGraph stages from live SSE events", () => {
    const snap = deriveExecutionGraph([
      { event: "run", data: { source_event: "run_started", status: "running" } },
      { event: "output", data: { source_event: "repository_discovered", entries: 12 } },
      { event: "step", data: { source_event: "plan_created", plan: ["edit api"] } },
      { event: "approval", data: { source_event: "approval_required", kind: "plan" } },
    ]);

    expect(snap.statuses.intake).toBe("succeeded");
    expect(snap.statuses.discover).toBe("succeeded");
    expect(snap.statuses.plan).toBe("succeeded");
    expect(snap.statuses.awaiting).toBe("waiting");
    expect(snap.activeNodeId).toBe("awaiting");
    expect(snap.detail).toContain("等待审批");
  });

  it("marks execute running on tool loops and finalize on success", () => {
    const snap = deriveExecutionGraph([
      { event: "run", data: { source_event: "run_started" } },
      { event: "output", data: { source_event: "repository_discovered" } },
      { event: "step", data: { source_event: "plan_created" } },
      { event: "approval", data: { source_event: "approval_decided", approved: true } },
      { event: "output", data: { source_event: "worktree_created", path: "/tmp/wt" } },
      { event: "output", data: { source_event: "model_turn", tool_calls: [{}], subtask_id: "main", content: "..." } },
      { event: "tool", data: { source_event: "tool_result", tool: "write_file", status: "succeeded", summary: "ok" } },
      { event: "terminal", data: { source_event: "verification_finished", command: "pytest", exit_code: 0, status: "succeeded" } },
      { event: "task_end", data: { source_event: "run_finished", status: "succeeded" } },
    ]);

    expect(snap.statuses.prepare_workspace).toBe("succeeded");
    expect(snap.statuses.execute).toBe("succeeded");
    expect(snap.statuses.verify).toBe("succeeded");
    expect(snap.statuses.finalize).toBe("succeeded");
    expect(snap.activeNodeId).toBeNull();
  });

  it("routes repair_started onto the repair node", () => {
    const snap = deriveExecutionGraph([
      { event: "run", data: { source_event: "run_started" } },
      { event: "terminal", data: { source_event: "verification_finished", exit_code: 1, status: "failed" } },
      { event: "output", data: { source_event: "repair_started", round: 1, error: "tests failed" } },
    ]);

    expect(snap.statuses.verify).toBe("failed");
    expect(snap.statuses.repair).toBe("running");
    expect(snap.activeNodeId).toBe("repair");
    expect(snap.detail).toContain("第 1 轮");
  });

  it("maps workflow role nodes onto the default graph", () => {
    const snap = deriveExecutionGraph([
      { event: "output", data: { source_event: "workflow_node_started", node_id: "n1", role: "implementer" } },
      { event: "output", data: { source_event: "workflow_node_finished", node_id: "n1", role: "implementer", failed: false } },
    ]);

    expect(snap.statuses.execute).toBe("succeeded");
  });

  it("normalizes namespaced workflow roles without inventing unknown stages", () => {
    const tester = deriveExecutionGraph([
      {
        event: "output",
        data: {
          source_event: "workflow_node_started",
          node_id: "quality-gate",
          role: "workflow.role:tester",
        },
      },
    ]);
    expect(tester.statuses.verify).toBe("running");
    expect(tester.activeNodeId).toBe("verify");

    const unknown = deriveExecutionGraph([
      {
        event: "output",
        data: {
          source_event: "workflow_node_started",
          node_id: "custom-agent",
          role: "custom-specialist",
        },
      },
    ]);
    expect(unknown.statuses.execute).toBe("idle");
    expect(unknown.activeNodeId).toBeNull();
  });
});
