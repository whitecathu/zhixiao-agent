// 所有接口请求/响应数据的 TS 类型声明

export interface ApiResponse<T = unknown> {
  code: number;
  message: string;
  data: T;
  trace_id?: string;
}

export interface PageData<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

// ---- 认证 ----
export interface User {
  id: number;
  username: string;
  email: string;
  nickname?: string | null;
  avatar_url?: string | null;
  last_login_at?: string | null;
}

export interface TokenOut {
  access_token: string;
  refresh_token: string;
  expires_in: number;
  user: User;
}

// ---- 空间 ----
export interface Space {
  id: number;
  name: string;
  description?: string | null;
  owner_id: number;
}

export interface SpaceMember {
  id: number;
  user_id: number;
  role: "super_admin" | "space_admin" | "member";
}

// ---- 任务 ----
export type TaskStatus = "awaiting_approval" | "queued" | "running" | "interrupted" | "succeeded" | "failed" | "cancelled";
export type PermissionMode = "read_only" | "edit" | "execute" | "full";

export interface TaskItem {
  id: number;
  space_id: number;
  user_id: number;
  repository_id: number;
  workflow_id?: number | null;
  agent_id?: number | null;
  title: string;
  prompt: string;
  status: TaskStatus;
  permission_mode: PermissionMode;
  execution_id?: string | null;
  current_step?: string | null;
  verification?: Record<string, unknown> | null;
  error_message?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface AgentStep {
  id: number;
  task_run_id: number;
  sequence: number;
  role: string;
  name: string;
  status: "pending" | "running" | "succeeded" | "failed" | "blocked";
  input?: Record<string, unknown> | null;
  output?: Record<string, unknown> | null;
  error_message?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface Repository {
  id: number;
  space_id: number;
  owner_id: number;
  name: string;
  clone_url?: string | null;
  root_path?: string | null;
  default_branch: string;
  status: string;
  settings?: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

export interface Approval {
  id: number;
  task_run_id: number;
  operation: string;
  reason: string;
  requested_by: number;
  decided_by?: number | null;
  status: "pending" | "approved" | "rejected";
  comment?: string | null;
  decided_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface Artifact {
  id: number;
  task_run_id: number;
  kind: "diff" | "test_report" | "log" | "dataset" | "adapter" | "report" | "other";
  name: string;
  path?: string | null;
  mime_type?: string | null;
  size: number;
  checksum?: string | null;
  metadata?: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

export interface ToolResult {
  status: "succeeded" | "failed" | "blocked";
  summary: string;
  next_actions: string[];
  artifacts: Array<Record<string, unknown>>;
  error_root_cause?: string | null;
  retry_hint?: string | null;
  stop_reason?: string | null;
}

export interface ToolInvocation {
  id: number;
  task_run_id?: number | null;
  run_step_id?: number | null;
  agent_name: string;
  tool_name: string;
  input?: Record<string, unknown> | null;
  result: ToolResult;
  status: string;
  duration_ms: number;
  created_at: string;
  updated_at: string;
}

export interface TestResult {
  id: string;
  command: string;
  status: "pending" | "running" | "passed" | "failed" | "skipped";
  duration_ms?: number;
  summary?: string;
}

export interface WorkflowDefinition {
  id: number;
  space_id: number;
  name: string;
  version: number;
  enabled: boolean;
  definition: {
    nodes: Array<{ id: string; role: string; label: string }>;
    edges: Array<{ source: string; target: string; condition?: string }>;
  };
  created_at: string;
  updated_at: string;
}

export interface AgentDefinition {
  id: number;
  space_id: number;
  name: string;
  role: string;
  system_prompt: string;
  tool_allowlist: string[];
  model_profile_id?: number | null;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface ToolDefinition {
  name: string;
  description: string;
  permission: PermissionMode;
  result_contract: Record<string, unknown>;
}

export interface ModelProfile {
  id: number;
  space_id: number;
  name: string;
  provider: "openai" | "xai" | "deepseek" | "qwen" | "vllm";
  model_name: string;
  base_url: string;
  api_key_env?: string | null;
  parameters?: Record<string, unknown> | null;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface FineTuneJob {
  id: number;
  space_id: number;
  base_model: string;
  dataset_artifact_id?: number | null;
  status: string;
  config: Record<string, unknown>;
  metrics?: Record<string, unknown> | null;
  adapter_artifact_id?: number | null;
  created_at: string;
  updated_at: string;
}

export interface EvaluationRun {
  id: number;
  space_id: number;
  model_profile_id?: number | null;
  dataset_name: string;
  status: string;
  metrics?: Record<string, number> | null;
  report_artifact_id?: number | null;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeEntity {
  id: number;
  space_id: number;
  name: string;
  entity_type: string;
  properties: Record<string, unknown>;
  source_refs: Array<Record<string, unknown>>;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeRelation {
  id: number;
  space_id: number;
  source_entity_id: number;
  target_entity_id: number;
  relation_type: string;
  properties: Record<string, unknown>;
  evidence: Array<Record<string, unknown>>;
  created_at: string;
  updated_at: string;
}

// ---- 知识 ----
export interface Knowledge {
  id: number;
  space_id: number;
  source_task_id?: number | null;
  type: "experience" | "template" | "knowledge" | "pitfall";
  title: string;
  content: string;
  summary?: string | null;
  tags?: string[] | null;
  category_path?: string | null;
  quality_score: number;
  usage_count: number;
  last_used_at?: string | null;
  status: string;
  created_at: string;
}

export interface SearchHit {
  knowledge_id: number;
  score: number;
  title: string;
  summary?: string;
  snippet: string;
  tags?: string[];
  category_path?: string | null;
  quality_score: number;
  source_task_id?: number | null;
}

// ---- 统计 ----
export interface SpaceOverview {
  total_tasks: number;
  succeeded: number;
  tasks_last_30d: number;
  knowledge_total: number;
  reuse_rate: number;
}

export interface AgentStat {
  agent_name: string;
  invocations: number;
  avg_duration_ms: number;
}

// ---- SSE ----
export interface SSEPayload {
  id?: string;
  sequence?: number;
  event: "run" | "step" | "tool" | "todo" | "approval" | "output" | "artifact" | "terminal" | "agent_start" | "agent_step" | "token" | "agent_end" | "task_end" | "error" | "knowledge_sediment" | "heartbeat" | "run_started" | "repository_discovered" | "plan_created" | "approval_required" | "approval_decided" | "tool_result" | "verification_finished" | "verification_skipped" | "run_finished";
  timestamp?: string;
  data: Record<string, unknown>;
}
