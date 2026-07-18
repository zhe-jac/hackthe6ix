import * as assert from "node:assert/strict";
import { test } from "node:test";

import {
  ProtocolError,
  encodeNotification,
  numberParam,
  parseNotification,
} from "../bridge/messages";

void test("protocol notification round trip", () => {
  const encoded = encodeNotification("editor.scroll", { lines: 4 }).trimEnd();

  const notification = parseNotification(encoded, 1024);

  assert.equal(notification.method, "editor.scroll");
  assert.equal(numberParam(notification.params, "lines"), 4);
});

void test("protocol rejects arrays as params", () => {
  assert.throws(
    () =>
      parseNotification(
        '{"jsonrpc":"2.0","method":"editor.scroll","params":[]}',
        1024,
      ),
    ProtocolError,
  );
});

void test("protocol enforces the encoded byte limit", () => {
  const line = encodeNotification("request.preview", {
    transcript: "x".repeat(2000),
  });

  assert.throws(() => parseNotification(line, 1024), /exceeds/u);
});
