import assert from "node:assert/strict";
import test from "node:test";

import {
  buildVoiceEditorCommandCatalog,
  commandContributionsFromManifests,
} from "../voice/editorCommandCatalog";

void test("the catalog keeps only available safe built-in commands", () => {
  const commands = buildVoiceEditorCommandCatalog(
    ["workbench.action.openSettings", "workbench.action.terminal.sendSequence"],
    [],
    [],
  );

  assert.deepEqual(
    commands.map((command) => command.id),
    ["workbench.action.openSettings"],
  );
  assert.equal(commands[0]?.requiresConfirmation, false);
});

void test("configured extension commands use parsed metadata and confirmation", () => {
  const contributions = commandContributionsFromManifests([
    {
      contributes: {
        commands: [
          {
            command: "example.preview",
            title: "Open Preview",
            category: "Example",
          },
        ],
      },
    },
  ]);
  const commands = buildVoiceEditorCommandCatalog(
    ["example.preview", "example.unconfigured"],
    ["example.preview", "example.missing", "example.preview"],
    contributions,
  );

  assert.deepEqual(commands, [
    {
      id: "example.preview",
      title: "Example: Open Preview",
      description:
        "Run this user-approved installed-extension command with no arguments.",
      requiresConfirmation: true,
    },
  ]);
});

void test("invalid command contribution metadata is ignored", () => {
  assert.deepEqual(
    commandContributionsFromManifests([
      null,
      { contributes: { commands: "not-an-array" } },
      { contributes: { commands: [{ command: "missing.title" }] } },
    ]),
    [],
  );
});
