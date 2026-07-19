import assert from "node:assert/strict";
import test from "node:test";

import type { VoiceEditorCommand } from "../voice/editorCommandCatalog";
import { voiceRouteFromToolCall, voiceRoutingTools } from "../voice/router";

const EDITOR_COMMAND: VoiceEditorCommand = {
  id: "workbench.action.openSettings",
  title: "Open Settings",
  description: "Open the graphical VS Code Settings editor.",
  requiresConfirmation: false,
};

void test("the model is offered every supported voice action", () => {
  assert.deepEqual(
    voiceRoutingTools([]).map((tool) => tool.function.name),
    [
      "open_workspace_file",
      "create_workspace_files",
      "go_to_workspace_symbol",
      "show_symbol_references",
      "undo_last_edit",
      "cancel_current_request",
      "answer_workspace_question",
      "edit_workspace",
      "unsupported_request",
    ],
  );
});

void test("eligible editor commands are offered as validated model choices", () => {
  const tools = voiceRoutingTools([EDITOR_COMMAND]);
  assert.deepEqual(
    tools.map((tool) => tool.function.name),
    [
      "open_workspace_file",
      "create_workspace_files",
      "go_to_workspace_symbol",
      "show_symbol_references",
      "undo_last_edit",
      "cancel_current_request",
      "answer_workspace_question",
      "edit_workspace",
      "execute_editor_command",
      "unsupported_request",
    ],
  );
  const commandTool = tools.find(
    (tool) => tool.function.name === "execute_editor_command",
  );
  assert.deepEqual(
    (
      commandTool?.function.parameters.properties as
        Record<string, unknown> | undefined
    )?.command,
    {
      type: "string",
      enum: ["workbench.action.openSettings"],
    },
  );
  assert.deepEqual(
    voiceRouteFromToolCall(
      "execute_editor_command",
      { command: EDITOR_COMMAND.id },
      "open settings",
      [EDITOR_COMMAND],
    ),
    { kind: "editorCommand", command: EDITOR_COMMAND },
  );
});

void test("model tool calls become executable local routes", () => {
  assert.deepEqual(
    voiceRouteFromToolCall(
      "open_workspace_file",
      { query: "src/platform.py" },
      "take me to platform dot py",
    ),
    { kind: "open", query: "src/platform.py" },
  );
  assert.deepEqual(
    voiceRouteFromToolCall(
      "create_workspace_files",
      { paths: ["test.py", "devpost.md"] },
      "make the files",
    ),
    { kind: "createMany", paths: ["test.py", "devpost.md"] },
  );
  assert.deepEqual(
    voiceRouteFromToolCall(
      "go_to_workspace_symbol",
      { query: "parseConfig" },
      "find the config parser",
    ),
    { kind: "symbol", query: "parseConfig" },
  );
  assert.deepEqual(
    voiceRouteFromToolCall("show_symbol_references", {}, "where is this used"),
    { kind: "references", query: undefined },
  );
});

void test("question and edit routes preserve the user's exact request", () => {
  const question = "Would changing this parser break callers?";
  const edit = "Make this function return early";

  assert.deepEqual(
    voiceRouteFromToolCall("answer_workspace_question", {}, question),
    { kind: "question", instruction: question },
  );
  assert.deepEqual(voiceRouteFromToolCall("edit_workspace", {}, edit), {
    kind: "edit",
    instruction: edit,
  });
});

void test("the model can explicitly decline an unsupported request", () => {
  assert.deepEqual(
    voiceRouteFromToolCall(
      "unsupported_request",
      { reason: "No available IDE action matches the request." },
      "do something with this",
    ),
    {
      kind: "unsupported",
      instruction: "do something with this",
      reason: "No available IDE action matches the request.",
    },
  );
});

void test("invalid model action arguments are rejected", () => {
  assert.throws(
    () => voiceRouteFromToolCall("open_workspace_file", {}, "open it"),
    /missing 'query'/u,
  );
  assert.throws(
    () =>
      voiceRouteFromToolCall(
        "create_workspace_files",
        { paths: [] },
        "create files",
      ),
    /invalid 'paths'/u,
  );
  assert.throws(
    () => voiceRouteFromToolCall("run_shell", {}, "run tests"),
    /unknown voice action/u,
  );
  assert.throws(
    () =>
      voiceRouteFromToolCall(
        "execute_editor_command",
        { command: "workbench.action.terminal.sendSequence" },
        "run a terminal command",
        [EDITOR_COMMAND],
      ),
    /ineligible editor command/u,
  );
});
