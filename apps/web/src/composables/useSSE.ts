/**
 * SSE 客户端 - 使用 fetch + ReadableStream 解析，便于携带 Authorization Header
 * EventSource 不支持自定义 Header，因此不用原生 EventSource
 */
import { getAuthToken } from "@/utils/auth";
import type { SSEPayload } from "@/types";

export interface SSEHandlers {
  onEvent?: (payload: SSEPayload) => void;
  onClose?: () => void;
  onError?: (e: unknown) => void;
}

export interface SSEOptions {
  lastEventId?: string | null;
  reconnect?: boolean;
  maxRetries?: number;
}

export interface SSEStream {
  cancel: () => void;
}

export function subscribeTask(taskId: number, handlers: SSEHandlers, options: SSEOptions = {}): SSEStream {
  const controller = new AbortController();
  const base = import.meta.env.VITE_API_PREFIX || "/api/v1";
  const url = `${base}/task-runs/${taskId}/events`;
  const token = getAuthToken();
  let lastEventId = options.lastEventId || "";
  let retryCount = 0;

  (async () => {
    while (!controller.signal.aborted) {
      try {
        const headers: Record<string, string> = {
          Authorization: token ? `Bearer ${token}` : "",
          Accept: "text/event-stream",
        };
        if (lastEventId) headers["Last-Event-ID"] = lastEventId;
        const resp = await fetch(url, { method: "GET", headers, signal: controller.signal });
        if (!resp.ok || !resp.body) throw new Error(`SSE ${resp.status}`);
        retryCount = 0;
        const reader = resp.body.getReader();
        const decoder = new TextDecoder("utf-8");
        let buffer = "";
        let reading = true;
        while (reading) {
          const { value, done } = await reader.read();
          if (done) {
            reading = false;
            break;
          }
          buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
          let idx = buffer.indexOf("\n\n");
          while (idx !== -1) {
            const payload = parseSSEChunk(buffer.slice(0, idx));
            buffer = buffer.slice(idx + 2);
            if (payload) {
              if (payload.id) lastEventId = payload.id;
              handlers.onEvent?.(payload);
            }
            idx = buffer.indexOf("\n\n");
          }
        }
        if (options.reconnect === false) break;
      } catch (e) {
        if (controller.signal.aborted) break;
        handlers.onError?.(e);
        retryCount += 1;
        if (retryCount > (options.maxRetries ?? 5)) break;
      }
      await wait(Math.min(1000 * 2 ** retryCount, 10000), controller.signal);
    }
    handlers.onClose?.();
  })();

  return { cancel: () => controller.abort() };
}

export function parseSSEChunk(chunk: string): SSEPayload | null {
  let event = "message";
  let id: string | undefined;
  const dataParts: string[] = [];
  for (const line of chunk.split("\n")) {
    if (!line) continue;
    if (line.startsWith(":")) continue; // comment / heartbeat
    const sep = line.indexOf(":");
    if (sep === -1) continue;
    const field = line.slice(0, sep);
    const value = line.slice(sep + 1).replace(/^ /, "");
    if (field === "event") event = value;
    if (field === "id") id = value;
    if (field === "data") dataParts.push(value);
  }
  if (!dataParts.length) return null;
  try {
    const payload = JSON.parse(dataParts.join("\n"));
    return { id, event: event as SSEPayload["event"], data: payload };
  } catch {
    return null;
  }
}

function wait(ms: number, signal: AbortSignal) {
  return new Promise<void>((resolve) => {
    const timer = window.setTimeout(resolve, ms);
    signal.addEventListener("abort", () => {
      window.clearTimeout(timer);
      resolve();
    }, { once: true });
  });
}
