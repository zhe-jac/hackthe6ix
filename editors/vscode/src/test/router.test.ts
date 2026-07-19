import assert from "node:assert/strict";
import test from "node:test";

import { routeVoiceRequest } from "../voice/router";

void test("router handles deterministic commands before model requests", () => {
  assert.deepEqual(routeVoiceRequest("open file config.py"), {
    kind: "open",
    query: "config.py",
  });
  assert.deepEqual(routeVoiceRequest("can you open plotform dot pi"), {
    kind: "open",
    query: "plotform dot pi",
  });
  assert.deepEqual(
    routeVoiceRequest('Create a new markdown file named "Hello."'),
    { kind: "create", path: "Hello.md" },
  );
  assert.deepEqual(routeVoiceRequest("Make a Python file called test.py."), {
    kind: "create",
    path: "test.py",
  });
  assert.deepEqual(
    routeVoiceRequest("could you generate a Python script called checks"),
    {
      kind: "create",
      path: "checks.py",
    },
  );
  assert.deepEqual(routeVoiceRequest("make me tools slash verify dot P Y"), {
    kind: "create",
    path: "tools/verify.py",
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

void test("router separates questions, edits, and unsupported requests", () => {
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
  assert.deepEqual(routeVoiceRequest("create a helper function"), {
    kind: "edit",
    instruction: "create a helper function",
  });
  assert.deepEqual(routeVoiceRequest("make this function return early"), {
    kind: "edit",
    instruction: "make this function return early",
  });
  assert.deepEqual(
    routeVoiceRequest(
      "create a simple for loop that counts from one to 10 and prints it in the terminal in test.py",
    ),
    {
      kind: "edit",
      instruction:
        "create a simple for loop that counts from one to 10 and prints it in the terminal in test.py",
    },
  );
  assert.deepEqual(routeVoiceRequest("do something with this"), {
    kind: "unsupported",
    instruction: "do something with this",
  });
});
