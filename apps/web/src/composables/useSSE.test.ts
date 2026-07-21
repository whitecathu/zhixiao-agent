import { describe, expect, it } from "vitest";
import { parseSSEChunk } from "./useSSE";

describe("parseSSEChunk", () => {
  it("parses resumable structured events", () => {
    const event = parseSSEChunk("id: 42-0\nevent: approval\ndata: {\"approval_id\":7,\"status\":\"pending\"}");
    expect(event).toEqual({
      id: "42-0",
      event: "approval",
      data: { approval_id: 7, status: "pending" },
    });
  });

  it("joins multi-line data and ignores malformed payloads", () => {
    expect(parseSSEChunk("event: output\ndata: {\"content\":\ndata: \"hello\"}"))
      .toMatchObject({ event: "output", data: { content: "hello" } });
    expect(parseSSEChunk("event: output\ndata: not-json")).toBeNull();
    expect(parseSSEChunk(": heartbeat")).toBeNull();
  });
});
