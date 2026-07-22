import { describe, expect, it } from "vitest";

import { taskStatusTag, taskStatusText } from "./status";

describe("status", () => {
  it("maps task status to localized label", () => {
    expect(taskStatusText("running")).toBe("执行中");
    expect(taskStatusText("succeeded")).toBe("已完成");
  });

  it("maps task status to tag type", () => {
    expect(taskStatusTag("failed")).toBe("danger");
    expect(taskStatusTag("succeeded")).toBe("success");
  });
});
