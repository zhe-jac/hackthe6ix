import assert from "node:assert/strict";
import test from "node:test";

import type { BridgeNotification } from "../bridge/messages";
import { parseChudvisInbound } from "../voice/protocol";

function notification(
  method: string,
  params: Record<string, unknown>,
): BridgeNotification {
  return { jsonrpc: "2.0", method, params };
}

void test("voice protocol validates states, request IDs, and transcripts", () => {
  assert.deepEqual(
    parseChudvisInbound(
      notification("voice.level", { level: 0.67, dbfs: -19.8 }),
    ),
    { method: "voice.level", level: 0.67, dbfs: -19.8 },
  );
  assert.deepEqual(
    parseChudvisInbound(
      notification("voice.request", {
        requestId: "9246c59a-98e6-4d77-82f0-c75567f9f807",
        transcript: "open file README.md",
      }),
    ),
    {
      method: "voice.request",
      requestId: "9246c59a-98e6-4d77-82f0-c75567f9f807",
      transcript: "open file README.md",
    },
  );
  assert.throws(
    () =>
      parseChudvisInbound(
        notification("voice.state", { state: "uploading", requestId: "valid" }),
      ),
    /voice state/u,
  );
  assert.throws(
    () =>
      parseChudvisInbound(
        notification("voice.partial", { requestId: "../bad", text: "x" }),
      ),
    /requestId/u,
  );
  assert.throws(
    () =>
      parseChudvisInbound(
        notification("voice.level", { level: 1.5, dbfs: -20 }),
      ),
    /microphone level/u,
  );
});
