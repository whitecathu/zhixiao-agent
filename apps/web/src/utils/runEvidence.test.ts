import { describe, expect, it } from "vitest";

import {
  MISSING_EVIDENCE,
  formatRunEvidence,
  serializeRunEvidence,
} from "./runEvidence";

function item(strip: ReturnType<typeof formatRunEvidence>, key: string) {
  const found = strip.items.find((entry) => entry.key === key);
  if (!found) throw new Error(`missing evidence item ${key}`);
  return found;
}

describe("formatRunEvidence", () => {
  it("shows API verification outcome, termination reason, and usage", () => {
    const strip = formatRunEvidence({
      permission_mode: "execute",
      verification: {
        passed: true,
        details: { outcome: "passed" },
      },
      termination_reason: "completed",
      usage_snapshot: {
        prompt_tokens: 1200,
        completion_tokens: 400,
        cost_usd: 0.12,
        model_turns: 3,
      },
    });

    expect(strip.title).toBe("运行证据");
    expect(item(strip, "permission_mode").value).toBe("execute");
    expect(item(strip, "verification").value).toBe("已通过");
    expect(item(strip, "verification").raw).toBe("passed");
    expect(item(strip, "verification").missing).toBe(false);
    expect(item(strip, "termination_reason").value).toBe("completed");
    expect(item(strip, "usage").value).toContain("1200");
    expect(item(strip, "usage").value).toContain("400");
    expect(item(strip, "usage").value).toContain("0.12");
    expect(item(strip, "usage").missing).toBe(false);

    const text = serializeRunEvidence(strip);
    expect(text).toContain("运行证据");
    expect(text).toContain("已通过");
    expect(text).toContain("completed");
    expect(text).toContain("1200");
  });

  it("shows 未回报 for missing verification, termination, and usage without fabricating success", () => {
    const strip = formatRunEvidence({
      permission_mode: "edit",
      verification: null,
      termination_reason: null,
      usage_snapshot: {},
    });

    expect(strip.items.map((entry) => entry.label)).toEqual([
      "权限模式",
      "验证结果",
      "终止原因",
      "用量",
    ]);
    expect(item(strip, "permission_mode").value).toBe("edit");
    expect(item(strip, "verification").value).toBe(MISSING_EVIDENCE);
    expect(item(strip, "verification").missing).toBe(true);
    expect(item(strip, "termination_reason").value).toBe(MISSING_EVIDENCE);
    expect(item(strip, "usage").value).toBe(MISSING_EVIDENCE);

    const text = serializeRunEvidence(strip);
    expect(text).toContain("运行证据");
    expect(text).toContain(MISSING_EVIDENCE);
    expect(text).not.toMatch(/通过/);
    expect(text).not.toMatch(/passed/i);

    const unloaded = serializeRunEvidence(formatRunEvidence(null));
    expect(unloaded).toContain(MISSING_EVIDENCE);
    expect(unloaded).not.toMatch(/通过/);
    expect(unloaded).not.toMatch(/passed/i);
  });

  it("does not claim 已通过 when only verification.passed is true", () => {
    const strip = formatRunEvidence({
      permission_mode: "edit",
      verification: { passed: true },
    });

    expect(item(strip, "verification").value).toBe(MISSING_EVIDENCE);
    expect(item(strip, "verification").missing).toBe(true);
    expect(item(strip, "verification").raw).toBeNull();

    const text = serializeRunEvidence(strip);
    expect(text).toContain(MISSING_EVIDENCE);
    expect(text).not.toContain("已通过");
    expect(text).not.toMatch(/通过/);
  });

  it("prefers details.outcome over a top-level outcome", () => {
    const strip = formatRunEvidence({
      permission_mode: "full",
      verification: {
        outcome: "skipped",
        details: { outcome: "failed" },
      },
    });
    expect(item(strip, "verification").value).toBe("失败");
    expect(item(strip, "verification").raw).toBe("failed");
  });

  it("uses top-level outcome when details are absent", () => {
    const strip = formatRunEvidence({
      permission_mode: "edit",
      verification: { outcome: "passed" },
    });
    expect(item(strip, "verification").value).toBe("已通过");
    expect(item(strip, "verification").raw).toBe("passed");
  });
});
