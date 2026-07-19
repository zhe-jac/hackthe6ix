import assert from "node:assert/strict";
import test from "node:test";

import {
  fileMatchScore,
  isSupportedCreateFilePath,
  normalizeSpokenFileQuery,
  requestedFilePath,
} from "../voice/fileIntent";

void test("spoken file names normalize common extensions", () => {
  assert.equal(normalizeSpokenFileQuery("plotform dot pi"), "plotform.py");
  assert.equal(
    normalizeSpokenFileQuery("source slash platform dot P Y"),
    "source/platform.py",
  );
});

void test("typed file creation adds the requested extension", () => {
  assert.equal(requestedFilePath("markdown", '"Hello."'), "Hello.md");
  assert.equal(
    requestedFilePath("python", "tools slash check"),
    "tools/check.py",
  );
  assert.equal(requestedFilePath(undefined, "notes.md"), "notes.md");
  assert.equal(isSupportedCreateFilePath("tools slash check dot P Y"), true);
  assert.equal(isSupportedCreateFilePath("this function return early"), false);
  assert.equal(
    isSupportedCreateFilePath(
      "a simple for loop that counts from one to 10 in test.py",
    ),
    false,
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
