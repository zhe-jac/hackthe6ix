import assert from "node:assert/strict";
import test from "node:test";

import { routeVoiceRequest } from "../voice/router";

void test("router handles deterministic commands before model requests", () => {
  assert.deepEqual(routeVoiceRequest("open file config.py"), {
    kind: "open",
    query: "config.py",
  });
  assert.deepEqual(routeVoiceRequest("go to function parseConfig"), {
    kind: "symbol",
    query: "parseConfig",
  });
  assert.deepEqual(routeVoiceRequest("show references to this"), {
    kind: "references",
    query: undefined,
  });
  assert.deepEqual(routeVoiceRequest("undo last edit"), { kind: "undo" });
  assert.deepEqual(routeVoiceRequest("never mind"), { kind: "cancel" });
});

void test("router never infers an edit from a question or ambiguous request", () => {
  assert.deepEqual(routeVoiceRequest("what should I change in this function"), {
    kind: "question",
    instruction: "what should I change in this function",
  });
  assert.deepEqual(routeVoiceRequest("tell me about this parser"), {
    kind: "question",
    instruction: "tell me about this parser",
  });
  assert.deepEqual(routeVoiceRequest("please fix the parser"), {
    kind: "edit",
    instruction: "please fix the parser",
  });
});
