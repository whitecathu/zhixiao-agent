import { afterEach, describe, expect, it, vi } from "vitest";
import { parseSSEChunk, subscribeTask } from "./useSSE";

vi.mock("@/utils/auth", () => ({
  getAuthToken: () => "tok",
  getSpaceId: () => 42,
}));

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

describe("subscribeTask", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("sends Authorization and X-Space-Id on the SSE fetch", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      body: null,
    });
    vi.stubGlobal("fetch", fetchMock);

    const stream = subscribeTask(9, {}, { reconnect: false, maxRetries: 0 });
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    stream.cancel();

    const init = fetchMock.mock.calls[0][1] as {
      headers: Record<string, string>;
    };
    const headers = init.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer tok");
    expect(headers["X-Space-Id"]).toBe("42");
    expect(headers.Accept).toBe("text/event-stream");
  });
});
