import assert from "node:assert/strict";
import test from "node:test";

import {
  fileMatchScore,
  normalizeSpokenFileQuery,
  referencedFileQueries,
} from "../voice/fileIntent";

void test("spoken file names normalize common extensions", () => {
  assert.equal(normalizeSpokenFileQuery("plotform dot pi"), "plotform.py");
  assert.equal(
    normalizeSpokenFileQuery("source slash platform dot P Y"),
    "source/platform.py",
  );
});

void test("file references are extracted from edit instructions", () => {
  assert.deepEqual(
    referencedFileQueries(
      "Write a for loop in test.py that prints each number.",
    ),
    ["test.py"],
  );
  assert.deepEqual(
    referencedFileQueries("Update source slash runner dot pi."),
    ["source/runner.py"],
  );
  assert.deepEqual(
    referencedFileQueries("Move the helper from source.py to target.py"),
    ["source.py", "target.py"],
  );
});

void test("file matching tolerates a bounded speech typo", () => {
  assert.equal(
    fileMatchScore("plotform dot pi", "src/chudvis/core/platform.py"),
    101,
  );
  assert.equal(
    fileMatchScore("platform.py", "src/chudvis/core/platform.py"),
    1,
  );
  assert.equal(fileMatchScore("platform.py", "README.md"), undefined);
});
