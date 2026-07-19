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

void test("edit proposal rejects empty originals and oversized operation lists", () => {
  assert.throws(
    () =>
      parseEditProposal({
        edits: [
          {
            path: "src/parser.ts",
            originalText: "",
            replacementText: "x",
            reason: "unsafe",
          },
        ],
      }),
    /originalText/u,
  );
  assert.throws(
    () => parseEditProposal({ edits: Array.from({ length: 101 }, () => ({})) }),
    /between 1 and 100/u,
  );
});
