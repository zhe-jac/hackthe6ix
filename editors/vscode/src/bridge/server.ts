import * as net from "node:net";

import {
  type BridgeNotification,
  PROTOCOL_VERSION,
  ProtocolError,
  encodeNotification,
  numberParam,
  parseNotification,
  stringParam,
} from "./messages";

const LOOPBACK_HOSTS = new Set(["127.0.0.1", "localhost", "::1"]);

export interface BridgeServerOptions {
  readonly host: string;
  readonly port: number;
  readonly sessionToken: string;
  readonly maxMessageBytes: number;
}

export type NotificationHandler = (
  notification: BridgeNotification,
) => Promise<void> | void;

export type BridgeStateHandler = (connected: boolean, detail: string) => void;

interface ClientState {
  readonly socket: net.Socket;
  buffer: string;
  authenticated: boolean;
}

export class BridgeServer {
  private server: net.Server | undefined;
  private client: ClientState | undefined;

  public constructor(
    private readonly options: BridgeServerOptions,
    private readonly handler: NotificationHandler,
    private readonly onState: BridgeStateHandler,
  ) {
    if (!LOOPBACK_HOSTS.has(options.host)) {
      throw new Error("Chudvis bridge must listen on a loopback host");
    }
    if (options.port < 0 || options.port > 65_535) {
      throw new Error("Chudvis bridge port is invalid");
    }
  }

  public async start(): Promise<number> {
    if (this.server !== undefined) {
      return this.addressPort();
    }
    this.server = net.createServer((socket) => this.accept(socket));
    this.server.on("error", (error) => {
      this.onState(false, `Bridge error: ${error.message}`);
    });
    await new Promise<void>((resolve, reject) => {
      const server = this.server;
      if (server === undefined) {
        reject(new Error("Bridge server was not created"));
        return;
      }
      const onError = (error: Error): void => reject(error);
      server.once("error", onError);
      server.listen(this.options.port, this.options.host, () => {
        server.off("error", onError);
        resolve();
      });
    });
    const port = this.addressPort();
    this.onState(false, `Bridge listening on ${this.options.host}:${port}`);
    return port;
  }

  public addressPort(): number {
    const address = this.server?.address();
    if (
      address === null ||
      address === undefined ||
      typeof address === "string"
    ) {
      return this.options.port;
    }
    return address.port;
  }

  private accept(socket: net.Socket): void {
    if (this.client !== undefined) {
      this.client.socket.destroy();
    }
    socket.setEncoding("utf8");
    socket.setNoDelay(true);
    const client: ClientState = { socket, buffer: "", authenticated: false };
    this.client = client;
    socket.on("data", (chunk: string) => this.receive(client, chunk));
    socket.on("error", (error) => {
      this.onState(false, `Bridge client error: ${error.message}`);
    });
    socket.on("close", () => {
      if (this.client === client) {
        this.client = undefined;
        this.onState(false, "Python runtime disconnected");
      }
    });
  }

  private receive(client: ClientState, chunk: string): void {
    client.buffer += chunk;
    if (
      Buffer.byteLength(client.buffer, "utf8") > this.options.maxMessageBytes &&
      !client.buffer.includes("\n")
    ) {
      this.reject(client, "Unterminated bridge message exceeds the size limit");
      return;
    }
    for (;;) {
      const newline = client.buffer.indexOf("\n");
      if (newline < 0) {
        return;
      }
      const line = client.buffer.slice(0, newline);
      client.buffer = client.buffer.slice(newline + 1);
      if (line.length === 0) {
        continue;
      }
      try {
        const message = parseNotification(line, this.options.maxMessageBytes);
        if (!client.authenticated) {
          this.authenticate(client, message);
        } else {
          void Promise.resolve(this.handler(message)).catch(
            (error: unknown) => {
              const detail =
                error instanceof Error
                  ? error.message
                  : "Unknown command error";
              this.sendStatus(`Command '${message.method}' failed: ${detail}`);
            },
          );
        }
      } catch (error: unknown) {
        const detail =
          error instanceof Error ? error.message : "Unknown protocol error";
        this.reject(client, detail);
        return;
      }
    }
  }

  private authenticate(client: ClientState, message: BridgeNotification): void {
    if (message.method !== "bridge.hello") {
      throw new ProtocolError("First bridge message must be bridge.hello");
    }
    const version = numberParam(message.params, "protocolVersion");
    const token = stringParam(message.params, "sessionToken");
    if (version !== PROTOCOL_VERSION) {
      throw new ProtocolError(`Unsupported protocol version ${version}`);
    }
    if (token !== this.options.sessionToken) {
      throw new ProtocolError("IDE bridge session token does not match");
    }
    client.authenticated = true;
    this.onState(true, "Python runtime connected");
    this.sendStatus("VS Code extension connected");
  }

  private reject(client: ClientState, detail: string): void {
    try {
      client.socket.write(
        encodeNotification("bridge.status", { message: detail }),
      );
    } finally {
      client.socket.destroy();
    }
  }

  public sendStatus(message: string): void {
    this.sendNotification("bridge.status", { message });
  }

  public sendNotification(
    method: string,
    params: Readonly<Record<string, unknown>> = {},
  ): void {
    const client = this.client;
    if (client?.authenticated === true && !client.socket.destroyed) {
      client.socket.write(encodeNotification(method, params));
    }
  }

  public async stop(): Promise<void> {
    const client = this.client;
    this.client = undefined;
    if (client !== undefined) {
      client.socket.destroy();
    }
    const server = this.server;
    this.server = undefined;
    if (server === undefined) {
      return;
    }
    await new Promise<void>((resolve) => {
      server.close(() => resolve());
    });
    this.onState(false, "Bridge stopped");
  }
}
