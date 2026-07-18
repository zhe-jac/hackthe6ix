import * as assert from "node:assert/strict";
import { test } from "node:test";

import { parsePorcelain } from "../review/porcelain";

void test("Git porcelain parser handles regular, untracked, and renamed paths", () => {
  const output =
    " M src/app.py\0?? src/new.ts\0R  src/new-name.py\0src/old-name.py\0";

  assert.deepEqual(parsePorcelain(output), [
    "src/app.py",
    "src/new.ts",
    "src/new-name.py",
  ]);
});
