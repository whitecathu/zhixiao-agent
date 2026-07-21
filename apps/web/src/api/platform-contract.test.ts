import { beforeEach, describe, expect, it, vi } from "vitest";

const requestMock = vi.hoisted(() => vi.fn());
vi.mock("@/utils/request", () => ({ request: requestMock }));

import { definitionApi, intelligenceApi, modelApi, repositoryApi, runApi, workflowApi } from "./agent";
import { taskApi } from "./task";

describe("platform API contract", () => {
  beforeEach(() => requestMock.mockReset());

  it("uses RepositoryCreate and TaskRun endpoints without legacy field aliases", async () => {
    await repositoryApi.create({ name: "local", root_path: "C:/repos/local", default_branch: "main" });
    expect(requestMock).toHaveBeenLastCalledWith({
      method: "POST", url: "/repositories",
      data: { name: "local", root_path: "C:/repos/local", default_branch: "main" },
    });

    await taskApi.create({
      repository_id: 9, title: "Fix API", prompt: "Fix the failing API contract test.",
      permission_mode: "edit",
    });
    expect(requestMock).toHaveBeenLastCalledWith({
      method: "POST", url: "/task-runs",
      data: {
        repository_id: 9, title: "Fix API", prompt: "Fix the failing API contract test.",
        permission_mode: "edit",
      },
    });
    await taskApi.list();
    expect(requestMock).toHaveBeenLastCalledWith({ method: "GET", url: "/task-runs" });
    await taskApi.get(12);
    expect(requestMock).toHaveBeenLastCalledWith({ method: "GET", url: "/task-runs/12" });
    await taskApi.control(12, "resume");
    expect(requestMock).toHaveBeenLastCalledWith({ method: "POST", url: "/task-runs/12/resume" });
  });

  it("uses the approval decision resource and unified diff response", async () => {
    await runApi.decide(31, "approved", "Proceed");
    expect(requestMock).toHaveBeenLastCalledWith({
      method: "POST", url: "/approvals/31/decision",
      data: { decision: "approved", comment: "Proceed" },
    });
    await runApi.diff(12);
    expect(requestMock).toHaveBeenLastCalledWith({ method: "GET", url: "/task-runs/12/diff" });
    await runApi.toolInvocations(12);
    expect(requestMock).toHaveBeenLastCalledWith({ method: "GET", url: "/task-runs/12/tool-invocations" });
  });

  it("creates versioned configuration resources with backend field names", async () => {
    await workflowApi.create({
      id: 22, name: "safe-edit", version: 2, enabled: true,
      definition: { nodes: [{ id: "plan", role: "planner", label: "Plan" }], edges: [] },
    });
    expect(requestMock).toHaveBeenLastCalledWith({
      method: "POST", url: "/workflows",
      data: {
        name: "safe-edit", version: 2, enabled: true,
        definition: { nodes: [{ id: "plan", role: "planner", label: "Plan" }], edges: [] },
      },
    });

    await definitionApi.createAgent({
      id: 5, name: "reviewer", role: "reviewer", system_prompt: "Review every diff.",
      tool_allowlist: ["git_diff"], enabled: true,
    });
    expect(requestMock).toHaveBeenLastCalledWith({
      method: "POST", url: "/agents",
      data: {
        name: "reviewer", role: "reviewer", system_prompt: "Review every diff.",
        tool_allowlist: ["git_diff"], model_profile_id: undefined, enabled: true,
      },
    });

    await modelApi.create({
      id: 3, name: "local", provider: "vllm", base_url: "http://vllm:8000/v1",
      model_name: "tiny", api_key_env: "VLLM_API_KEY", enabled: true,
    });
    expect(requestMock).toHaveBeenLastCalledWith({
      method: "POST", url: "/models",
      data: {
        name: "local", provider: "vllm", base_url: "http://vllm:8000/v1",
        model_name: "tiny", api_key_env: "VLLM_API_KEY", parameters: null, enabled: true,
      },
    });
  });

  it("uses collection responses and exact evaluation and fine-tune schemas", async () => {
    await intelligenceApi.evaluations();
    expect(requestMock).toHaveBeenLastCalledWith({ method: "GET", url: "/evaluations" });
    await intelligenceApi.createEvaluation({ dataset_name: "smoke-v1", model_profile_id: 2 });
    expect(requestMock).toHaveBeenLastCalledWith({
      method: "POST", url: "/evaluations",
      data: { dataset_name: "smoke-v1", model_profile_id: 2 },
    });
    await modelApi.createFineTune({ base_model: "tiny", dataset_artifact_id: 8, config: { rank: 4 } });
    expect(requestMock).toHaveBeenLastCalledWith({
      method: "POST", url: "/fine-tunes",
      data: { base_model: "tiny", dataset_artifact_id: 8, config: { rank: 4 } },
    });
  });
});
