import { beforeEach, describe, expect, it, vi } from "vitest";

const requestMock = vi.hoisted(() => vi.fn());
vi.mock("@/utils/request", () => ({ request: requestMock }));

import { intelligenceApi, workflowApi } from "./agent";
import { observabilityApi, onboardingApi } from "./product";

describe("product expansion API contract", () => {
  beforeEach(() => requestMock.mockReset());

  it("loads low-cardinality observability summary by window", async () => {
    await observabilityApi.summary("7d");
    expect(requestMock).toHaveBeenCalledWith({
      method: "GET", url: "/observability/summary", params: { window: "7d" },
    });
  });

  it("supports resumable, skippable and replayable onboarding", async () => {
    await onboardingApi.state();
    expect(requestMock).toHaveBeenLastCalledWith({ method: "GET", url: "/onboarding/me" });
    await onboardingApi.complete("connect_repository");
    expect(requestMock).toHaveBeenLastCalledWith({ method: "POST", url: "/onboarding/me/steps/connect_repository/complete" });
    await onboardingApi.skip();
    expect(requestMock).toHaveBeenLastCalledWith({ method: "POST", url: "/onboarding/me/skip" });
    await onboardingApi.replay();
    expect(requestMock).toHaveBeenLastCalledWith({ method: "POST", url: "/onboarding/me/replay" });
    await onboardingApi.updateConfig({ recommended_template: "cross-stack", default_workflow_id: 3 });
    expect(requestMock).toHaveBeenLastCalledWith({
      method: "PUT", url: "/onboarding/config",
      data: { recommended_template: "cross-stack", default_workflow_id: 3 },
    });
  });

  it("publishes workflow versions and replays the version fixed to a run", async () => {
    await workflowApi.publish(12);
    expect(requestMock).toHaveBeenLastCalledWith({ method: "POST", url: "/workflows/12/publish" });
    await workflowApi.versions(12);
    expect(requestMock).toHaveBeenLastCalledWith({ method: "GET", url: "/workflows/12/versions" });
    await workflowApi.replay(44);
    expect(requestMock).toHaveBeenLastCalledWith({ method: "GET", url: "/task-runs/44/workflow-replay" });
  });

  it("bounds graph exploration and requests evidence-bearing neighbors", async () => {
    await intelligenceApi.exploreGraph({ query: "LangGraph", entity_types: ["library"], depth: 1, limit: 100 });
    expect(requestMock).toHaveBeenLastCalledWith({
      method: "POST", url: "/knowledge/graph/explore",
      data: { query: "LangGraph", entity_types: ["library"], depth: 1, limit: 100 },
    });
    await intelligenceApi.exploreGraph({ entity_id: 9, depth: 1, limit: 100 });
    expect(requestMock).toHaveBeenLastCalledWith({
      method: "POST", url: "/knowledge/graph/explore",
      data: { entity_id: 9, depth: 1, limit: 100 },
    });
  });
});
