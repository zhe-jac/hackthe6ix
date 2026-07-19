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

  await assert.rejects(client.listModels(), (error: unknown) => {
    assert(error instanceof Error);
    assert.match(error.message, /HTTP status 500/u);
    assert.doesNotMatch(error.message, /sensitive/u);
    return true;
  });
});
