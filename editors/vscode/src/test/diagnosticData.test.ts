import assert from "node:assert/strict";
import test from "node:test";

import {
  redactDiagnosticValue,
  summarizeDiagnosticPayload,
} from "../diagnostics/diagnosticData";

void test("diagnostic redaction removes nested credentials while retaining useful payloads", () => {
  assert.deepEqual(
    redactDiagnosticValue({
      transcript: "fix the parser",
      sessionToken: "bridge-secret",
      nested: {
        api_key: "model-secret",
        Authorization: "Bearer token",
        source: "const safe = true;",
      },
    }),
    {
      transcript: "fix the parser",
      sessionToken: "[redacted]",
      nested: {
        api_key: "[redacted]",
        Authorization: "[redacted]",
        source: "const safe = true;",
      },
    },
  );
});

void test("disabled payload capture reports shape instead of contents", () => {
  const summary = summarizeDiagnosticPayload({
    content: "private source",
    model_name: "model-a",
  });

  assert.deepEqual(summary, {
    captured: false,
    type: "object",
    fields: ["content", "model_name"],
    characters: 51,
  });
  assert.doesNotMatch(JSON.stringify(summary), /private source/u);
});
