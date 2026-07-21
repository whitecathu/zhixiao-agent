import { request } from "@/utils/request";
import type {
  AgentDefinition,
  Approval,
  Artifact,
  EvaluationRun,
  FineTuneJob,
  KnowledgeEntity,
  KnowledgeRelation,
  ModelProfile,
  Repository,
  ToolDefinition,
  ToolInvocation,
  WorkflowDefinition,
} from "@/types";

export interface RepositoryCreate {
  name: string;
  clone_url?: string;
  root_path?: string;
  default_branch?: string;
}

export interface DiffResponse {
  task_run_id: number;
  unified_diff: string;
  verified: boolean;
}

export const repositoryApi = {
  list: () => request<Repository[]>({ method: "GET", url: "/repositories" }),
  create: (data: RepositoryCreate) =>
    request<Repository>({ method: "POST", url: "/repositories", data }),
};

export const runApi = {
  approvals: (runId: number) => request<Approval[]>({ method: "GET", url: `/task-runs/${runId}/approvals` }),
  decide: (approvalId: number, decision: "approved" | "rejected", comment?: string) =>
    request<Approval>({ method: "POST", url: `/approvals/${approvalId}/decision`, data: { decision, comment } }),
  artifacts: (runId: number) => request<Artifact[]>({ method: "GET", url: `/task-runs/${runId}/artifacts` }),
  diff: (runId: number) => request<DiffResponse>({ method: "GET", url: `/task-runs/${runId}/diff` }),
  toolInvocations: (runId: number) => request<ToolInvocation[]>({ method: "GET", url: `/task-runs/${runId}/tool-invocations` }),
};

function workflowPayload(data: Partial<WorkflowDefinition>) {
  return { name: data.name, version: data.version, definition: data.definition, enabled: data.enabled };
}

export const workflowApi = {
  list: () => request<WorkflowDefinition[]>({ method: "GET", url: "/workflows" }),
  create: (data: Partial<WorkflowDefinition>) =>
    request<WorkflowDefinition>({ method: "POST", url: "/workflows", data: workflowPayload(data) }),
};

function agentPayload(data: Partial<AgentDefinition>) {
  return {
    name: data.name,
    role: data.role,
    system_prompt: data.system_prompt,
    tool_allowlist: data.tool_allowlist ?? [],
    model_profile_id: data.model_profile_id,
    enabled: data.enabled,
  };
}

export const definitionApi = {
  agents: () => request<AgentDefinition[]>({ method: "GET", url: "/agents" }),
  createAgent: (data: Partial<AgentDefinition>) =>
    request<AgentDefinition>({ method: "POST", url: "/agents", data: agentPayload(data) }),
  tools: () => request<ToolDefinition[]>({ method: "GET", url: "/tools" }),
};

function modelPayload(data: Partial<ModelProfile>) {
  return {
    name: data.name,
    provider: data.provider,
    base_url: data.base_url,
    model_name: data.model_name,
    api_key_env: data.api_key_env || null,
    parameters: data.parameters || null,
    enabled: data.enabled,
  };
}

export const modelApi = {
  profiles: () => request<ModelProfile[]>({ method: "GET", url: "/models" }),
  create: (data: Partial<ModelProfile>) =>
    request<ModelProfile>({ method: "POST", url: "/models", data: modelPayload(data) }),
  fineTunes: () => request<FineTuneJob[]>({ method: "GET", url: "/fine-tunes" }),
  createFineTune: (data: { base_model: string; dataset_artifact_id?: number; config?: Record<string, unknown> }) =>
    request<FineTuneJob>({ method: "POST", url: "/fine-tunes", data }),
};

export const intelligenceApi = {
  graph: () => request<{ entities: KnowledgeEntity[]; relations: KnowledgeRelation[] }>({ method: "GET", url: "/knowledge/graph" }),
  evaluations: () => request<EvaluationRun[]>({ method: "GET", url: "/evaluations" }),
  createEvaluation: (data: { dataset_name: string; model_profile_id?: number }) =>
    request<EvaluationRun>({ method: "POST", url: "/evaluations", data }),
};
