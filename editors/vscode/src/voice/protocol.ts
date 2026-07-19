import {
  type BridgeNotification,
  numberParam,
  ProtocolError,
  stringParam,
} from "../bridge/messages";

export const VOICE_STATES = [
  "ready",
  "connecting",
  "listening",
  "understanding",
  "editing",
  "speaking",
  "error",
  "paused",
] as const;

export type VoiceState = (typeof VOICE_STATES)[number];

export type ChudvisInbound =
  | {
      readonly method: "voice.state";
      readonly state: VoiceState;
      readonly requestId: string | undefined;
      readonly detail: string;
    }
  | {
      readonly method: "voice.level";
      readonly level: number;
      readonly dbfs: number;
    }
  | {
      readonly method: "voice.partial";
      readonly requestId: string;
      readonly text: string;
    }
  | {
      readonly method: "voice.request";
      readonly requestId: string;
      readonly transcript: string;
    }
  | {
      readonly method: "edit.approve" | "edit.cancel";
      readonly requestId: string;
    };

function optionalString(
  params: Readonly<Record<string, unknown>>,
  name: string,
  maximum: number,
): string | undefined {
  const value = params[name];
  if (value === undefined) {
    return undefined;
  }
  if (typeof value !== "string" || value.length > maximum) {
    throw new ProtocolError(`Bridge parameter '${name}' is invalid`);
  }
  return value;
}

function requestId(params: Readonly<Record<string, unknown>>): string {
  const value = stringParam(params, "requestId");
  if (!/^[\w-]{1,100}$/u.test(value)) {
    throw new ProtocolError("Bridge requestId is invalid");
  }
  return value;
}

export function parseChudvisInbound(
  notification: BridgeNotification,
): ChudvisInbound | undefined {
  const params = notification.params;
  switch (notification.method) {
    case "voice.state": {
      const rawState = stringParam(params, "state");
      const state = VOICE_STATES.find((candidate) => candidate === rawState);
      if (state === undefined) {
        throw new ProtocolError("Bridge voice state is invalid");
      }
      const id = optionalString(params, "requestId", 100);
      if (id !== undefined && !/^[\w-]+$/u.test(id)) {
        throw new ProtocolError("Bridge requestId is invalid");
      }
      return {
        method: "voice.state",
        state,
        requestId: id,
        detail: optionalString(params, "detail", 500) ?? "",
      };
    }
    case "voice.level": {
      const level = numberParam(params, "level");
      const dbfs = numberParam(params, "dbfs");
      if (level < 0 || level > 1 || dbfs < -100 || dbfs > 0) {
        throw new ProtocolError("Bridge microphone level is invalid");
      }
      return { method: "voice.level", level, dbfs };
    }
    case "voice.partial": {
      const text = stringParam(params, "text");
      if (text.length > 16_000) {
        throw new ProtocolError("Partial transcript is too large");
      }
      return { method: "voice.partial", requestId: requestId(params), text };
    }
    case "voice.request": {
      const transcript = stringParam(params, "transcript").trim();
      if (transcript.length === 0 || transcript.length > 16_000) {
        throw new ProtocolError("Committed transcript is invalid");
      }
      return {
        method: "voice.request",
        requestId: requestId(params),
        transcript,
      };
    }
    case "edit.approve":
    case "edit.cancel":
      return { method: notification.method, requestId: requestId(params) };
    default:
      return undefined;
  }
}
