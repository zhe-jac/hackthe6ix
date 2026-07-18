export const PROTOCOL_VERSION = 1;
export const JSONRPC_VERSION = "2.0";

export interface BridgeNotification {
  readonly jsonrpc: "2.0";
  readonly method: string;
  readonly params: Readonly<Record<string, unknown>>;
}

export class ProtocolError extends Error {}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function parseNotification(
  line: string,
  maxBytes: number,
): BridgeNotification {
  if (Buffer.byteLength(line, "utf8") > maxBytes) {
    throw new ProtocolError(`Message exceeds the ${maxBytes}-byte limit`);
  }
  let value: unknown;
  try {
    value = JSON.parse(line) as unknown;
  } catch (error: unknown) {
    const detail =
      error instanceof Error ? error.message : "unknown JSON error";
    throw new ProtocolError(`Invalid protocol JSON: ${detail}`);
  }
  if (!isRecord(value)) {
    throw new ProtocolError("Protocol message must be an object");
  }
  if (value.jsonrpc !== JSONRPC_VERSION) {
    throw new ProtocolError("Unsupported JSON-RPC version");
  }
  if (typeof value.method !== "string" || value.method.length === 0) {
    throw new ProtocolError("Protocol notification requires a method");
  }
  if (!isRecord(value.params)) {
    throw new ProtocolError("Protocol notification params must be an object");
  }
  return {
    jsonrpc: JSONRPC_VERSION,
    method: value.method,
    params: value.params,
  };
}

export function encodeNotification(
  method: string,
  params: Readonly<Record<string, unknown>> = {},
): string {
  if (method.length === 0) {
    throw new ProtocolError("Protocol method must not be empty");
  }
  return `${JSON.stringify({ jsonrpc: JSONRPC_VERSION, method, params })}\n`;
}

export function numberParam(
  params: Readonly<Record<string, unknown>>,
  name: string,
): number {
  const value = params[name];
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new ProtocolError(`Parameter '${name}' must be a finite number`);
  }
  return value;
}

export function stringParam(
  params: Readonly<Record<string, unknown>>,
  name: string,
): string {
  const value = params[name];
  if (typeof value !== "string") {
    throw new ProtocolError(`Parameter '${name}' must be a string`);
  }
  return value;
}

export function booleanParam(
  params: Readonly<Record<string, unknown>>,
  name: string,
): boolean {
  const value = params[name];
  if (typeof value !== "boolean") {
    throw new ProtocolError(`Parameter '${name}' must be a boolean`);
  }
  return value;
}
