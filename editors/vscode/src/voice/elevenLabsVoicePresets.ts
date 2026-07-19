export type ElevenLabsVoicePresetId = "chud" | "jarvis";

export interface ElevenLabsVoicePreset {
  readonly id: ElevenLabsVoicePresetId;
  readonly label: string;
  readonly description: string;
  readonly accountVoiceName: string;
}

export type ElevenLabsPresetVoiceIds = Readonly<
  Record<ElevenLabsVoicePresetId, string>
>;

interface VoiceSearchPage {
  readonly voices?: unknown;
  readonly has_more?: unknown;
  readonly next_page_token?: unknown;
}

type FetchLike = (
  input: string,
  init?: RequestInit,
) => Promise<Pick<Response, "ok" | "status" | "json" | "text">>;

const ELEVENLABS_VOICES_URL = "https://api.elevenlabs.io/v2/voices";
const MAX_SEARCH_PAGES = 20;

export const ELEVENLABS_VOICE_PRESETS: readonly ElevenLabsVoicePreset[] = [
  {
    id: "chud",
    label: "CHUD",
    description: "The default gamer-chud character voice",
    accountVoiceName: "CHUD",
  },
  {
    id: "jarvis",
    label: "JARVIS",
    description: "The polished British AI-assistant voice",
    accountVoiceName: "JARVIS",
  },
] as const;

export function getElevenLabsVoicePreset(
  id: ElevenLabsVoicePresetId,
): ElevenLabsVoicePreset {
  const preset = ELEVENLABS_VOICE_PRESETS.find(
    (candidate) => candidate.id === id,
  );
  if (preset === undefined) {
    throw new Error(`Unknown ElevenLabs voice preset: ${id}`);
  }
  return preset;
}

export function isElevenLabsVoicePresetId(
  value: unknown,
): value is ElevenLabsVoicePresetId {
  return value === "chud" || value === "jarvis";
}

async function responseErrorDetail(
  response: Pick<Response, "text">,
): Promise<string> {
  let raw = "";
  try {
    raw = (await response.text()).trim().slice(0, 2_000);
    const value: unknown = JSON.parse(raw);
    if (typeof value === "object" && value !== null && !Array.isArray(value)) {
      const detail = (value as Record<string, unknown>).detail;
      if (typeof detail === "string" && detail.trim().length > 0) {
        return detail.trim().slice(0, 500);
      }
      if (
        typeof detail === "object" &&
        detail !== null &&
        !Array.isArray(detail)
      ) {
        const message = (detail as Record<string, unknown>).message;
        if (typeof message === "string" && message.trim().length > 0) {
          return message.trim().slice(0, 500);
        }
      }
    }
  } catch {
    // Some ElevenLabs failures are plain text rather than JSON.
  }
  return raw.slice(0, 500);
}

async function requireSuccessfulResponse(
  response: Pick<Response, "ok" | "status" | "text">,
  apiKey: string,
): Promise<void> {
  if (response.ok) {
    return;
  }
  let detail = await responseErrorDetail(response);
  if (apiKey.length > 0) {
    detail = detail.split(apiKey).join("[redacted]");
  }
  const reason = detail.length > 0 ? `: ${detail}` : "";
  throw new Error(
    `ElevenLabs voice lookup failed with HTTP ${response.status}${reason}`,
  );
}

function matchingVoiceIds(
  value: unknown,
  exactName: string,
): {
  readonly ids: readonly string[];
  readonly hasMore: boolean;
  readonly nextPageToken?: string;
} {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("ElevenLabs returned an invalid voice-list response");
  }
  const page = value as VoiceSearchPage;
  if (!Array.isArray(page.voices) || typeof page.has_more !== "boolean") {
    throw new Error("ElevenLabs returned an invalid voice-list response");
  }

  const ids = new Set<string>();
  for (const raw of page.voices) {
    if (typeof raw !== "object" || raw === null || Array.isArray(raw)) {
      continue;
    }
    const voice = raw as Record<string, unknown>;
    if (voice.name !== exactName) {
      continue;
    }
    if (
      typeof voice.voice_id !== "string" ||
      voice.voice_id.length === 0 ||
      voice.voice_id.length > 100
    ) {
      throw new Error(
        `ElevenLabs returned an invalid voice ID for account voice "${exactName}"`,
      );
    }
    ids.add(voice.voice_id);
  }

  if (!page.has_more) {
    return { ids: [...ids], hasMore: false };
  }
  if (
    typeof page.next_page_token !== "string" ||
    page.next_page_token.length === 0 ||
    page.next_page_token.length > 2_000
  ) {
    throw new Error("ElevenLabs voice-list pagination was invalid");
  }
  return {
    ids: [...ids],
    hasMore: true,
    nextPageToken: page.next_page_token,
  };
}

async function findVoiceIdByExactName(
  apiKey: string,
  exactName: string,
  fetcher: FetchLike,
): Promise<string> {
  const ids = new Set<string>();
  const seenPageTokens = new Set<string>();
  let nextPageToken: string | undefined;

  for (let pageNumber = 0; pageNumber < MAX_SEARCH_PAGES; pageNumber += 1) {
    const url = new URL(ELEVENLABS_VOICES_URL);
    url.searchParams.set("page_size", "100");
    url.searchParams.set("search", exactName);
    url.searchParams.set("voice_type", "non-community");
    url.searchParams.set("include_total_count", "false");
    if (nextPageToken !== undefined) {
      url.searchParams.set("next_page_token", nextPageToken);
    }
    const response = await fetcher(url.toString(), {
      headers: { "xi-api-key": apiKey },
      signal: AbortSignal.timeout(15_000),
    });
    await requireSuccessfulResponse(response, apiKey);
    const page = matchingVoiceIds(await response.json(), exactName);
    for (const id of page.ids) {
      ids.add(id);
    }
    if (!page.hasMore) {
      break;
    }
    const token = page.nextPageToken;
    if (token === undefined || seenPageTokens.has(token)) {
      throw new Error("ElevenLabs voice-list pagination repeated a page token");
    }
    seenPageTokens.add(token);
    nextPageToken = token;
    if (pageNumber === MAX_SEARCH_PAGES - 1) {
      throw new Error("ElevenLabs voice lookup exceeded the pagination limit");
    }
  }

  if (ids.size === 0) {
    throw new Error(
      `ElevenLabs account voice "${exactName}" was not found; the name must match exactly`,
    );
  }
  if (ids.size > 1) {
    throw new Error(
      `Multiple ElevenLabs account voices are named "${exactName}"; rename duplicates so exactly one remains`,
    );
  }
  const voiceId = ids.values().next().value;
  if (voiceId === undefined) {
    throw new Error(`ElevenLabs account voice "${exactName}" was not found`);
  }
  return voiceId;
}

export async function resolveElevenLabsPresetVoiceIds(
  apiKey: string,
  fetcher: FetchLike = fetch,
): Promise<ElevenLabsPresetVoiceIds> {
  const [chud, jarvis] = await Promise.all([
    findVoiceIdByExactName(apiKey, "CHUD", fetcher),
    findVoiceIdByExactName(apiKey, "JARVIS", fetcher),
  ]);
  return { chud, jarvis };
}
