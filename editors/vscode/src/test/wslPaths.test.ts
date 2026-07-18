import * as assert from "node:assert/strict";
import { test } from "node:test";

import { wslDistribution, wslUncPath } from "../platform/wslPaths";

void test("WSL remote authority converts to a Windows UNC path", () => {
  assert.equal(wslDistribution("wsl+Ubuntu-22.04"), "Ubuntu-22.04");
  assert.equal(
    wslUncPath("wsl+Ubuntu-22.04", "/home/dylan/project/app.py"),
    "\\\\wsl.localhost\\Ubuntu-22.04\\home\\dylan\\project\\app.py",
  );
});

void test("non-WSL and malformed authorities are rejected", () => {
  assert.equal(wslDistribution("ssh-remote+server"), undefined);
  assert.equal(wslDistribution("wsl+bad%2Fname"), undefined);
  assert.equal(wslDistribution("wsl+bad%ZZname"), undefined);
  assert.equal(wslUncPath("wsl+Ubuntu", "relative/path"), undefined);
});
