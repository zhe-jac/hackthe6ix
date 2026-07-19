import assert from "node:assert/strict";
import test from "node:test";

import {
  isExcludedWorkspacePath,
  normalizeRelativePath,
} from "../workspace/pathPolicy";

void test("workspace path policy rejects traversal and absolute paths", () => {
  assert.throws(() => normalizeRelativePath("../outside.ts"), /unsafe/u);
  assert.throws(() => normalizeRelativePath("/etc/passwd"), /relative/u);
  assert.throws(() => normalizeRelativePath("C:\\secret.txt"), /relative/u);
  assert.equal(normalizeRelativePath("src\\parser.ts"), "src/parser.ts");
});

void test("workspace path policy excludes dependencies, secrets, and binaries", () => {
  assert(isExcludedWorkspacePath("node_modules/pkg/index.js"));
  assert(isExcludedWorkspacePath(".env.local"));
  assert(isExcludedWorkspacePath(".envrc"));
  assert(isExcludedWorkspacePath("id_ed25519"));
  assert(isExcludedWorkspacePath("config/credentials.json"));
  assert(isExcludedWorkspacePath("assets/model.onnx"));
  assert(!isExcludedWorkspacePath("src/config.ts"));
});
