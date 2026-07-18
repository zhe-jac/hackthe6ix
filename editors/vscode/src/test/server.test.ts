import * as assert from "node:assert/strict";
import * as net from "node:net";
import { once } from "node:events";
import { test } from "node:test";

import {
  encodeNotification,
  type BridgeNotification,
} from "../bridge/messages";
import { BridgeServer } from "../bridge/server";

void test("bridge authenticates then dispatches notifications", async (context) => {
  let resolveNotification:
    ((notification: BridgeNotification) => void) | undefined;
  const received = new Promise<BridgeNotification>((resolve) => {
    resolveNotification = resolve;
  });
  const server = new BridgeServer(
    {
      host: "127.0.0.1",
      port: 0,
      sessionToken: "test-token",
      maxMessageBytes: 4096,
    },
    (notification) => resolveNotification?.(notification),
    () => undefined,
  );
  const port = await server.start();
  const socket = net.createConnection({ host: "127.0.0.1", port });
  context.after(async () => {
    socket.destroy();
    await server.stop();
  });
  await once(socket, "connect");

  socket.write(
    encodeNotification("bridge.hello", {
      protocolVersion: 1,
      client: "test",
      sessionToken: "test-token",
    }),
  );
  socket.write(encodeNotification("editor.scroll", { lines: 7 }));

  const notification = await received;
  assert.equal(notification.method, "editor.scroll");
  assert.deepEqual(notification.params, { lines: 7 });
});

void test("bridge rejects an invalid session token", async (context) => {
  const server = new BridgeServer(
    {
      host: "127.0.0.1",
      port: 0,
      sessionToken: "expected",
      maxMessageBytes: 4096,
    },
    () => assert.fail("Unauthenticated notification was dispatched"),
    () => undefined,
  );
  const port = await server.start();
  const socket = net.createConnection({ host: "127.0.0.1", port });
  context.after(async () => {
    socket.destroy();
    await server.stop();
  });
  await once(socket, "connect");
  const closed = once(socket, "close");

  socket.write(
    encodeNotification("bridge.hello", {
      protocolVersion: 1,
      client: "test",
      sessionToken: "wrong",
    }),
  );

  const [data] = (await once(socket, "data")) as [Buffer];
  assert.match(data.toString("utf8"), /session token does not match/u);
  await closed;
});
