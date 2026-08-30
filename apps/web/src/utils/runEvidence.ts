export const MISSING_EVIDENCE = "未回报";
export const RUN_EVIDENCE_TITLE = "运行证据";

export type RunEvidenceKey = "permission_mode" | "verification" | "termination_reason" | "usage";

export interface RunEvidenceItem {
  key: RunEvidenceKey;
  label: string;
  value: string;
  missing: boolean;
  /** API outcome string when verification reported one; never inferred. */
  raw?: string | null;
}

export interface RunEvidenceStrip {
  title: typeof RUN_EVIDENCE_TITLE;
  items: RunEvidenceItem[];
}

export interface RunEvidenceSource {
  permission_mode?: string | null;
  verification?: Record<string, unknown> | null;
  termination_reason?: string | null;
  usage_snapshot?: Record<string, unknown> | null;
}

const OUTCOME_LABEL: Record<string, string> = {
  passed: "已通过",
  failed: "失败",
  skipped: "已跳过",
  blocked: "已阻断",
};

function asRecord(value: unknown): Record<string, unknown> | null {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  return null;
}

function asNonEmptyString(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed || null;
}

function asFiniteNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

/** Prefer `verification.details.outcome`, then `verification.outcome`. Never infers passed. */
export function readVerificationOutcome(
  verification: Record<string, unknown> | null | undefined,
): string | null {
  const rec = asRecord(verification);
  if (!rec) return null;
  const details = asRecord(rec.details);
  return asNonEmptyString(details?.outcome) ?? asNonEmptyString(rec.outcome);
}

function formatOutcomeLabel(outcome: string): string {
  return OUTCOME_LABEL[outcome] ?? outcome;
}

function formatCostUsd(value: number): string {
  if (value === 0) return "$0";
  const digits = Math.abs(value) < 0.01 ? 4 : 2;
  return `$${value.toFixed(digits)}`;
}

export function formatUsageSnapshot(
  snapshot: Record<string, unknown> | null | undefined,
): { value: string; missing: boolean } {
  const rec = asRecord(snapshot);
  if (!rec) return { value: MISSING_EVIDENCE, missing: true };

  const parts: string[] = [];
  const prompt = asFiniteNumber(rec.prompt_tokens);
  const completion = asFiniteNumber(rec.completion_tokens);
  if (prompt != null || completion != null) {
    if (prompt != null && completion != null) {
      parts.push(`${prompt} / ${completion} tokens`);
    } else if (prompt != null) {
      parts.push(`${prompt} prompt tokens`);
    } else {
      parts.push(`${completion} completion tokens`);
    }
  }

  const cost = asFiniteNumber(rec.cost_usd);
  if (cost != null) parts.push(formatCostUsd(cost));

  const turns = asFiniteNumber(rec.model_turns);
  if (turns != null) parts.push(`${turns} 回合`);

  const toolCalls = asFiniteNumber(rec.tool_calls);
  if (toolCalls != null) parts.push(`${toolCalls} 次工具`);

  if (!parts.length) return { value: MISSING_EVIDENCE, missing: true };
  return { value: parts.join(" · "), missing: false };
}

function formatVerification(
  verification: Record<string, unknown> | null | undefined,
): Pick<RunEvidenceItem, "value" | "missing" | "raw"> {
  const outcome = readVerificationOutcome(verification);
  if (outcome) {
    return { value: formatOutcomeLabel(outcome), missing: false, raw: outcome };
  }
  // `passed: true` without an outcome is not treated as harness success.
  return { value: MISSING_EVIDENCE, missing: true, raw: null };
}

function missingItem(key: RunEvidenceKey, label: string): RunEvidenceItem {
  return { key, label, value: MISSING_EVIDENCE, missing: true, raw: null };
}

export function formatRunEvidence(task: RunEvidenceSource | null | undefined): RunEvidenceStrip {
  const permission = asNonEmptyString(task?.permission_mode);
  const termination = asNonEmptyString(task?.termination_reason);
  const verification = formatVerification(task?.verification ?? null);
  const usage = formatUsageSnapshot(task?.usage_snapshot ?? null);

  return {
    title: RUN_EVIDENCE_TITLE,
    items: [
      permission
        ? { key: "permission_mode", label: "权限模式", value: permission, missing: false }
        : missingItem("permission_mode", "权限模式"),
      {
        key: "verification",
        label: "验证结果",
        value: verification.value,
        missing: verification.missing,
        raw: verification.raw,
      },
      termination
        ? { key: "termination_reason", label: "终止原因", value: termination, missing: false }
        : missingItem("termination_reason", "终止原因"),
      {
        key: "usage",
        label: "用量",
        value: usage.value,
        missing: usage.missing,
      },
    ],
  };
}

export function serializeRunEvidence(strip: RunEvidenceStrip): string {
  return [strip.title, ...strip.items.flatMap((item) => [item.label, item.value])].join(" ");
}
