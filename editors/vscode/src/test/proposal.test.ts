import assert from "node:assert/strict";
import test from "node:test";

import { parseEditProposal } from "../edits/proposal";

void test("edit proposal accepts exact bounded replacement operations", () => {
  assert.deepEqual(
    parseEditProposal({
      edits: [
        {
          path: "src/parser.ts",
          originalText: "return false;",
          replacementText: "return true;",
          reason: "Correct the predicate",
        },
      ],
    }),
    {
      edits: [
        {
          path: "src/parser.ts",
          originalText: "return false;",
          replacementText: "return true;",
          reason: "Correct the predicate",
        },
      ],
    },
  );
});

void test("edit proposal accepts empty-file insertions", () => {
  assert.deepEqual(
    parseEditProposal({
      edits: [
        {
          path: "test.py",
          originalText: "",
          replacementText: "for number in range(1, 11):\n    print(number)\n",
          reason: "Populate the empty file",
        },
      ],
    }),
    {
      edits: [
        {
          path: "test.py",
          originalText: "",
          replacementText: "for number in range(1, 11):\n    print(number)\n",
          reason: "Populate the empty file",
        },
      ],
    },
  );
});

void test("edit proposal rejects oversized operation lists", () => {
  assert.throws(
    () => parseEditProposal({ edits: Array.from({ length: 101 }, () => ({})) }),
    /between 1 and 100/u,
  );
});
