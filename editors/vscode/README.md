# Chudvis

This extension is the semantic editor half of Chudvis IDE mode. The Python runtime performs
local gaze, two-hand gestures, “Chudvis” wake detection, and activated ElevenLabs speech I/O. The
extension handles deterministic navigation, streams stateless Backboard explanations, validates
exact-text edit proposals, opens native diffs for scope expansion, and provides guarded Undo.

Use **Chudvis: Configure Backboard API Key** to store the provider key in VS Code SecretStorage.
The sidebar shows microphone/request state, partial transcripts, answers, edit targets, applied
summaries, review actions, Undo, and Clear Memory. Basic navigation and questions remain silent;
only a successful code edit (or short edit failure) can produce an ElevenLabs TTS response.

The bridge listens only on the configured loopback address. Camera frames, microphone audio,
source code, full transcripts, provider reasoning, API keys, and TTS bytes are not written to the
extension output channel. Post-wake microphone audio is sent by Python to ElevenLabs, while only
the resolved source/context is sent by this extension to Backboard.

See the repository's main README and `docs/ide-mode.md` for installation and usage.
