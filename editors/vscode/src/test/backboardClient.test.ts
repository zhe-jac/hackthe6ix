import assert from "node:assert/strict";
import test from "node:test";

import {
  BackboardClient,
  SseDecoder,
  type FetchLike,
} from "../model/backboardClient";

void test("SSE decoder handles split events and ignores completion markers", () => {
  const decoder = new SseDecoder();
  assert.deepEqual(decoder.push('data: {"type":"content_'), []);
  assert.deepEqual(
    decoder.push('streaming","content":"hello"}\n\ndata: [DONE]\n\n'),
    [{ type: "content_streaming", content: "hello" }],
  );
});

void test("Backboard client sends authenticated model query and validates response", async () => {
  let observedUrl = "";
  let observedKey = "";
  const fetcher: FetchLike = (input, init) => {
    observedUrl = input;
    observedKey = new Headers(init?.headers).get("X-API-Key") ?? "";
    return Promise.resolve(
      new Response(
        JSON.stringify({
          models: [
            {
              provider: "anthropic",
              name: "edit-model",
              context_limit: 100_000,
              supports_tools: true,
            },
          ],
        }),
        { status: 200 },
      ),
    );
  };
  const client = new BackboardClient(
    "secret-key",
    5_000,
    fetcher,
    "https://example.test/api",
  );

  const models = await client.listModels(undefined, "anthropic");

  assert.match(observedUrl, /provider=anthropic/u);
  assert.equal(observedKey, "secret-key");
  assert.deepEqual(models, [
    {
      provider: "anthropic",
      name: "edit-model",
      contextLimit: 100_000,
      supportsTools: true,
    },
  ]);
});

void test("Backboard HTTP errors do not expose response contents", async () => {
  const fetcher: FetchLike = () =>
    Promise.resolve(new Response("sensitive echoed source", { status: 500 }));
  const client = new BackboardClient("secret-key", 5_000, fetcher);
  const diagnostics: unknown[] = [];
  client.setDiagnosticObserver((event) => diagnostics.push(event));

  await assert.rejects(client.listModels(), (error: unknown) => {
    assert(error instanceof Error);
    assert.match(error.message, /HTTP status 500/u);
    assert.doesNotMatch(error.message, /sensitive/u);
    return true;
  });
  assert.deepEqual(diagnostics[1], {
    phase: "error",
    path: "/models?model_type=llm&limit=500",
    method: "GET",
    status: 500,
    durationMs: (diagnostics[1] as { durationMs: number }).durationMs,
    payload: "sensitive echoed source",
    error: "Backboard request failed with HTTP status 500",
  });
});

void test("Backboard diagnostics observe exact request and response payloads without credentials", async () => {
  const fetcher: FetchLike = (_input, init) =>
    Promise.resolve(
      new Response(
        JSON.stringify({ status: "REQUIRES_ACTION", content: "result" }),
        { status: 200, headers: init?.headers },
      ),
    );
  const client = new BackboardClient(
    "never-log-this-key",
    5_000,
    fetcher,
    "https://example.test/api",
  );
  const diagnostics: unknown[] = [];
  client.setDiagnosticObserver((event) => diagnostics.push(event));

  await client.sendMessage({ content: "exact prompt", model_name: "model-a" });

  assert.deepEqual(diagnostics, [
    {
      phase: "request",
      path: "/threads/messages",
      method: "POST",
      payload: { content: "exact prompt", model_name: "model-a" },
    },
    {
      phase: "response",
      path: "/threads/messages",
      method: "POST",
      status: 200,
      durationMs: (diagnostics[1] as { durationMs: number }).durationMs,
      payload: { status: "REQUIRES_ACTION", content: "result" },
    },
  ]);
  assert.doesNotMatch(JSON.stringify(diagnostics), /never-log-this-key/u);
});
