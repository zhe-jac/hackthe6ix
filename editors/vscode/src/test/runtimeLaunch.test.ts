import * as assert from "node:assert/strict";
import { test } from "node:test";

import { runtimeLaunchPlan } from "../runtime/launch";

void test("Windows launches the packaged native PowerShell runtime", () => {
  const plan = runtimeLaunchPlan("win32", "C:\\ext\\runtime", "C:\\state", {
    mode: "ide",
    preview: true,
    voice: false,
    uvExecutable: "C:\\tools\\uv.exe",
    pythonVersion: "3.12",
    extraArguments: ["--camera", "1"],
    bridge: { host: "127.0.0.1", port: 49152, sessionToken: "secret" },
  });

  assert.equal(plan.command, "powershell.exe");
  assert.deepEqual(plan.args.slice(-5), [
    "ide",
    "--preview",
    "--no-voice",
    "--camera",
    "1",
  ]);
  assert.equal(plan.environment.CHUDVIS_UV, "C:\\tools\\uv.exe");
  assert.equal(plan.environment.CHUDVIS_IDE_PORT, "49152");
  assert.equal(plan.environment.CHUDVIS_IDE_SESSION_TOKEN, "secret");
});

void test("diagnostics use the same two-hand tracker as IDE mode", () => {
  const plan = runtimeLaunchPlan("linux", "/extension/runtime", "/state", {
    mode: "diagnostics",
    preview: false,
    voice: true,
    uvExecutable: "uv",
    pythonVersion: "3.11",
    extraArguments: [],
    bridge: undefined,
  });

  assert.equal(plan.command, "uv");
  assert.deepEqual(plan.args.slice(-3), ["chudvis", "test", "--ide"]);
  assert.equal(plan.environment.UV_PROJECT_ENVIRONMENT, "/state/venv");
});
