const DEFAULT_BASE_URL = "https://app.backboard.io/api";
const MAX_RESPONSE_BYTES = 2 * 1024 * 1024;
const MAX_SSE_EVENT_BYTES = 262_144;

export type FetchLike = (
  input: string,
  init?: RequestInit,
) => Promise<Response>;

export interface BackboardModel {
  readonly provider: string;
  readonly name: string;
  readonly contextLimit: number;
  readonly supportsTools: boolean;
}

function objectValue(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`Backboard ${label} response is invalid`);
  }
  return value as Record<string, unknown>;
}

function stringValue(
  value: unknown,
  label: string,
  required = true,
): string | undefined {
  if (value === undefined || value === null) {
    if (!required) {
      return undefined;
    }
    throw new Error(`Backboard response is missing ${label}`);
  }
  if (typeof value !== "string" || value.length > MAX_RESPONSE_BYTES) {
    throw new Error(`Backboard response ${label} is invalid`);
  }
  return value;
}

async function boundedResponseText(response: Response): Promise<string> {
  if (response.body === null) {
    return "";
  }
  const reader = (
    response.body as unknown as ReadableStream<Uint8Array>
  ).getReader();
  const decoder = new TextDecoder();
  let received = 0;
  let result = "";
  for (;;) {
    const chunk = await reader.read();
    if (chunk.done) {
      result += decoder.decode();
      return result;
    }
    received += chunk.value.byteLength;
    if (received > MAX_RESPONSE_BYTES) {
      await reader.cancel();
      throw new Error("Backboard response exceeded the size limit");
    }
    result += decoder.decode(chunk.value, { stream: true });
  }
}

export class SseDecoder {
  private buffer = "";

  public push(chunk: string): readonly unknown[] {
    this.buffer += chunk.replaceAll("\r\n", "\n");
    if (this.buffer.length > MAX_SSE_EVENT_BYTES * 2) {
      throw new Error("Backboard SSE buffer exceeded the size limit");
    }
    const events: unknown[] = [];
    for (;;) {
      const boundary = this.buffer.indexOf("\n\n");
      if (boundary < 0) {
        return events;
      }
      const block = this.buffer.slice(0, boundary);
      this.buffer = this.buffer.slice(boundary + 2);
      if (Buffer.byteLength(block, "utf8") > MAX_SSE_EVENT_BYTES) {
        throw new Error("Backboard SSE event exceeded the size limit");
      }
      const data = block
        .split("\n")
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).trimStart())
        .join("\n");
      if (data.length === 0 || data === "[DONE]") {
        continue;
      }
      events.push(JSON.parse(data) as unknown);
    }
  }
}

interface TimedSignal {
  readonly signal: AbortSignal;
  dispose(): void;
}

interface TimedResponse {
  readonly response: Response;
  dispose(): void;
}

function timedSignal(
  external: AbortSignal | undefined,
  timeoutMs: number,
): TimedSignal {
  const controller = new AbortController();
  const timer = setTimeout(
    () => controller.abort(new Error("Backboard request timed out")),
    timeoutMs,
  );
  const abort = (): void => controller.abort(external?.reason);
  external?.addEventListener("abort", abort, { once: true });
  if (external?.aborted === true) {
    abort();
  }
  return {
    signal: controller.signal,
    dispose: () => {
      clearTimeout(timer);
      external?.removeEventListener("abort", abort);
    },
  };
}

export interface StreamResult {
  readonly threadId: string | undefined;
  readonly runId: string | undefined;
  readonly content: string;
}

export class BackboardClient {
  public constructor(
    private readonly apiKey: string,
    private readonly timeoutMs: number,
    private readonly fetcher: FetchLike = fetch,
    private readonly baseUrl = DEFAULT_BASE_URL,
  ) {
    if (apiKey.trim().length === 0) {
      throw new Error("Backboard API key is not configured");
    }
  }

  private async fetch(
    path: string,
    init: RequestInit,
    external?: AbortSignal,
  ): Promise<TimedResponse> {
    const timed = timedSignal(external, this.timeoutMs);
    try {
      const headers = new Headers(init.headers);
      headers.set("Content-Type", "application/json");
      headers.set("X-API-Key", this.apiKey);
      const response = await this.fetcher(`${this.baseUrl}${path}`, {
        ...init,
        headers,
        signal: timed.signal,
      });
      if (!response.ok) {
        try {
          await boundedResponseText(response);
          throw new Error(
            `Backboard request failed with HTTP status ${response.status}`,
          );
        } finally {
          timed.dispose();
        }
      }
      return { response, dispose: () => timed.dispose() };
    } catch (error: unknown) {
      timed.dispose();
      throw error;
    }
  }

  public async json(
    path: string,
    method: "GET" | "POST" | "DELETE",
    body?: unknown,
    signal?: AbortSignal,
  ): Promise<Record<string, unknown>> {
    const timed = await this.fetch(
      path,
      {
        method,
        body: body === undefined ? undefined : JSON.stringify(body),
      },
      signal,
    );
    try {
      const text = await boundedResponseText(timed.response);
      if (text.length === 0) {
        return {};
      }
      return objectValue(JSON.parse(text) as unknown, "JSON");
    } finally {
      timed.dispose();
    }
  }

  public async listModels(
    signal?: AbortSignal,
    provider?: string,
  ): Promise<readonly BackboardModel[]> {
    const providerQuery =
      provider === undefined ? "" : `&provider=${encodeURIComponent(provider)}`;
    const result = await this.json(
      `/models?model_type=llm&limit=500${providerQuery}`,
      "GET",
      undefined,
      signal,
    );
    if (!Array.isArray(result.models)) {
      throw new Error("Backboard models response is invalid");
    }
    return result.models.flatMap((raw): BackboardModel[] => {
      if (typeof raw !== "object" || raw === null || Array.isArray(raw)) {
        return [];
      }
      const model = raw as Record<string, unknown>;
      if (
        typeof model.provider !== "string" ||
        typeof model.name !== "string"
      ) {
        return [];
      }
      return [
        {
          provider: model.provider,
          name: model.name,
          contextLimit:
            typeof model.context_limit === "number" ? model.context_limit : 0,
          supportsTools: model.supports_tools === true,
        },
      ];
    });
  }

  public async createAssistant(
    body: unknown,
    signal?: AbortSignal,
  ): Promise<string> {
    const result = await this.json("/assistants", "POST", body, signal);
    return stringValue(result.assistant_id, "assistant_id") ?? "";
  }

  public async createThread(
    assistantId: string,
    signal?: AbortSignal,
  ): Promise<string> {
    const result = await this.json(
      `/assistants/${encodeURIComponent(assistantId)}/threads`,
      "POST",
      {},
      signal,
    );
    return stringValue(result.thread_id, "thread_id") ?? "";
  }

  public async deleteThread(threadId: string): Promise<void> {
    await this.json(`/threads/${encodeURIComponent(threadId)}`, "DELETE");
  }

  public async deleteAssistant(assistantId: string): Promise<void> {
    await this.json(`/assistants/${encodeURIComponent(assistantId)}`, "DELETE");
  }

  public async sendMessage(
    body: unknown,
    signal?: AbortSignal,
  ): Promise<Record<string, unknown>> {
    return this.json("/threads/messages", "POST", body, signal);
  }

  public async submitToolOutputs(
    body: unknown,
    signal?: AbortSignal,
  ): Promise<Record<string, unknown>> {
    return this.json("/threads/tool-outputs", "POST", body, signal);
  }

  public async cancelRun(threadId: string, runId: string): Promise<void> {
    await this.json(
      `/threads/${encodeURIComponent(threadId)}/runs/${encodeURIComponent(runId)}/cancel`,
      "POST",
      {},
    );
  }

  public async streamMessage(
    body: unknown,
    onContent: (chunk: string) => void,
    signal?: AbortSignal,
    onIdentifiers?: (
      threadId: string | undefined,
      runId: string | undefined,
    ) => void,
  ): Promise<StreamResult> {
    const timed = await this.fetch(
      "/threads/messages",
      { method: "POST", body: JSON.stringify(body) },
      signal,
    );
    try {
      if (timed.response.body === null) {
        throw new Error("Backboard streaming response is empty");
      }
      const decoder = new TextDecoder();
      const sse = new SseDecoder();
      const reader = (
        timed.response.body as unknown as ReadableStream<Uint8Array>
      ).getReader();
      let threadId: string | undefined;
      let runId: string | undefined;
      let content = "";
      let received = 0;
      for (;;) {
        const chunk = await reader.read();
        if (chunk.done) {
          break;
        }
        received += chunk.value.byteLength;
        if (received > MAX_RESPONSE_BYTES) {
          await reader.cancel();
          throw new Error("Backboard stream exceeded the size limit");
        }
        for (const raw of sse.push(
          decoder.decode(chunk.value, { stream: true }),
        )) {
          const event = objectValue(raw, "SSE event");
          threadId =
            stringValue(event.thread_id, "thread_id", false) ?? threadId;
          runId = stringValue(event.run_id, "run_id", false) ?? runId;
          onIdentifiers?.(threadId, runId);
          if (event.type === "content_streaming") {
            const next = stringValue(event.content, "content", false) ?? "";
            content += next;
            if (content.length > 256_000) {
              throw new Error("Backboard answer exceeded the size limit");
            }
            if (next.length > 0) {
              onContent(next);
            }
          }
          if (event.type === "error") {
            throw new Error(
              stringValue(event.message, "error", false) ??
                "Backboard stream failed",
            );
          }
        }
      }
      return { threadId, runId, content };
    } finally {
      timed.dispose();
    }
  }
}

export function backboardString(
  response: Readonly<Record<string, unknown>>,
  field: string,
  required = true,
): string | undefined {
  return stringValue(response[field], field, required);
}
import type { ReadableStream } from "node:stream/web";
