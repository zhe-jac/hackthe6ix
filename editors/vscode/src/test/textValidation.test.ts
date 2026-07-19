import assert from "node:assert/strict";
import test from "node:test";

import {
  assertNonOverlapping,
  matchesUndoGuard,
  uniqueTextRange,
} from "../edits/textValidation";

void test("exact text matching requires one unique occurrence", () => {
  assert.deepEqual(uniqueTextRange("before target after", "target"), {
    startOffset: 7,
    endOffset: 13,
  });
  assert.throws(() => uniqueTextRange("none", "target"), /exactly once/u);
  assert.throws(
    () => uniqueTextRange("target target", "target"),
    /exactly once/u,
  );
  assert.throws(() => uniqueTextRange("aaa", "aa"), /exactly once/u);
  assert.deepEqual(uniqueTextRange("", ""), {
    startOffset: 0,
    endOffset: 0,
  });
  assert.throws(() => uniqueTextRange("text", ""), /only for an empty file/u);
});

void test("overlap validation permits adjacent edits but rejects intersections", () => {
  assert.doesNotThrow(() =>
    assertNonOverlapping(
      [
        { startOffset: 0, endOffset: 4 },
        { startOffset: 4, endOffset: 8 },
      ],
      "file.ts",
    ),
  );
  assert.throws(
    () =>
      assertNonOverlapping(
        [
          { startOffset: 2, endOffset: 6 },
          { startOffset: 4, endOffset: 8 },
        ],
        "file.ts",
      ),
    /overlap/u,
  );
  assert.throws(
    () =>
      assertNonOverlapping(
        [
          { startOffset: 0, endOffset: 0 },
          { startOffset: 0, endOffset: 0 },
        ],
        "empty.py",
      ),
    /overlap/u,
  );
});

void test("Undo guard requires both the applied version and exact applied snapshot", () => {
  assert(matchesUndoGuard("applied", 4, "applied", 4));
  assert(!matchesUndoGuard("later change", 4, "applied", 4));
  assert(!matchesUndoGuard("applied", 5, "applied", 4));
});
