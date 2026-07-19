import assert from "node:assert/strict";
import test from "node:test";

import {
  ELEVENLABS_VOICE_PRESETS,
  getElevenLabsVoicePreset,
  isElevenLabsVoicePresetId,
  resolveElevenLabsPresetVoiceIds,
} from "../voice/elevenLabsVoicePresets";

function jsonResponse(status: number, value: unknown): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

void test("exposes only exact account names CHUD and JARVIS with CHUD first", () => {
  assert.deepEqual(
    ELEVENLABS_VOICE_PRESETS.map((preset) => preset.accountVoiceName),
    ["CHUD", "JARVIS"],
  );
  assert.equal(ELEVENLABS_VOICE_PRESETS[0]?.id, "chud");
  assert.equal(getElevenLabsVoicePreset("jarvis").label, "JARVIS");
  assert.equal(isElevenLabsVoicePresetId("chud"), true);
  assert.equal(isElevenLabsVoicePresetId("other"), false);
});

void test("resolves CHUD and JARVIS from exact account voice names", async () => {
  const observedUrls: string[] = [];
  const result = await resolveElevenLabsPresetVoiceIds(
    "secret-api-key",
    (url) => {
      observedUrls.push(url);
      const search = new URL(url).searchParams.get("search");
      return Promise.resolve(
        jsonResponse(200, {
          voices: [
            { voice_id: "wrong-case", name: search?.toLowerCase() },
            { voice_id: `${search}-voice-id`, name: search },
          ],
          has_more: false,
          next_page_token: null,
        }),
      );
    },
  );

  assert.deepEqual(result, {
    chud: "CHUD-voice-id",
    jarvis: "JARVIS-voice-id",
  });
  assert.equal(observedUrls.length, 2);
  for (const urlText of observedUrls) {
    const url = new URL(urlText);
    assert.equal(
      url.origin + url.pathname,
      "https://api.elevenlabs.io/v2/voices",
    );
    assert.equal(url.searchParams.get("page_size"), "100");
    assert.equal(url.searchParams.get("voice_type"), "non-community");
  }
});

void test("follows pagination while resolving an exact voice name", async () => {
  const pageCounts = new Map<string, number>();
  const result = await resolveElevenLabsPresetVoiceIds(
    "secret-api-key",
    (url) => {
      const parsed = new URL(url);
      const name = parsed.searchParams.get("search");
      assert.ok(name);
      const page = (pageCounts.get(name) ?? 0) + 1;
      pageCounts.set(name, page);
      return Promise.resolve(
        page === 1
          ? jsonResponse(200, {
              voices: [],
              has_more: true,
              next_page_token: `${name}-next`,
            })
          : jsonResponse(200, {
              voices: [{ voice_id: `${name}-id`, name }],
              has_more: false,
              next_page_token: null,
            }),
      );
    },
  );

  assert.deepEqual(result, { chud: "CHUD-id", jarvis: "JARVIS-id" });
  assert.deepEqual(Object.fromEntries(pageCounts), { CHUD: 2, JARVIS: 2 });
});

void test("reports a missing exact account voice", async () => {
  await assert.rejects(
    resolveElevenLabsPresetVoiceIds("secret-api-key", (url) => {
      const name = new URL(url).searchParams.get("search");
      return Promise.resolve(
        jsonResponse(200, {
          voices:
            name === "JARVIS"
              ? [{ voice_id: "jarvis-id", name: "JARVIS" }]
              : [{ voice_id: "lowercase-id", name: "chud" }],
          has_more: false,
          next_page_token: null,
        }),
      );
    }),
    /account voice "CHUD" was not found.*match exactly/u,
  );
});

void test("reports duplicate exact account voice names", async () => {
  await assert.rejects(
    resolveElevenLabsPresetVoiceIds("secret-api-key", (url) => {
      const name = new URL(url).searchParams.get("search");
      return Promise.resolve(
        jsonResponse(200, {
          voices:
            name === "CHUD"
              ? [
                  { voice_id: "chud-one", name: "CHUD" },
                  { voice_id: "chud-two", name: "CHUD" },
                ]
              : [{ voice_id: "jarvis-id", name: "JARVIS" }],
          has_more: false,
          next_page_token: null,
        }),
      );
    }),
    /Multiple ElevenLabs account voices are named "CHUD"/u,
  );
});

void test("redacts the API key from voice lookup errors", async () => {
  const apiKey = "very-secret-api-key";
  await assert.rejects(
    resolveElevenLabsPresetVoiceIds(apiKey, () =>
      Promise.resolve(
        jsonResponse(401, {
          detail: { message: `Invalid credential ${apiKey}` },
        }),
      ),
    ),
    (error: unknown) => {
      assert.ok(error instanceof Error);
      assert.match(error.message, /Invalid credential \[redacted\]/u);
      assert.doesNotMatch(error.message, new RegExp(apiKey, "u"));
      return true;
    },
  );
});
