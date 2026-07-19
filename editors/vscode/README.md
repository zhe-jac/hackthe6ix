# Chudvis

This extension owns the complete Chudvis IDE-mode lifecycle. It launches its packaged native Python
runtime for local gaze, two-hand gestures, “Chudvis” wake detection, and activated ElevenLabs
speech I/O. A tool-capable Backboard model selects and parameterizes each voice action. In-process
extension services execute bounded navigation, stream stateless Backboard explanations, validate
exact-text edit proposals, open native diffs for scope expansion, and provide guarded Undo.

Voice actions can safely create new workspace text files, and open-file execution normalizes spoken
extensions and tolerates small transcription errors. Creation rejects secret/excluded paths and
existing files; ambiguous open matches use a native Quick Pick. Intent selection and command
arguments come from a structured model tool call, not a keyword or regular-expression router.
Safe no-argument workbench commands are discovered from the active VS Code command registry, so
requests such as opening Settings, opening a terminal, showing the Command Palette, and switching
views execute as native VS Code actions. Additional installed-extension command IDs may be opted in
with `chudvis.voice.additionalCommands`; they require native confirmation before every execution.

Use **Chudvis: Calibrate Gaze**, **Chudvis: Test Tracking Safely**, **Chudvis: Start Gaze, Gesture,
and Voice Controls**, and **Chudvis: Stop Gaze, Gesture, and Voice Controls**. Activation leaves the
runtime off until the toggle shortcut, status item, or an explicit Start command is used. A separate
terminal or `uv run` command is not required after the extension is installed.

Use `Ctrl+Alt+G` on Windows/Linux or `Cmd+Alt+G` on macOS to toggle all live controls. Clicking the
Chudvis status-bar item performs the same toggle. The sidebar includes synchronized **Start/Stop
Controls**, **Test Tracking**, and **Recalibrate Gaze** buttons. Its compact hand table groups inputs
under no hand, editor hand (physical right by default), navigator hand (physical left by default),
or either hand.

The sidebar also shows Backboard and ElevenLabs setup status. Enter either key there or use the
matching **Configure ... API Key** command; both are stored in VS Code SecretStorage. The saved
ElevenLabs key is injected only into the supervised native process. Workspace `.env` files are not
loaded. The ElevenLabs account must contain voices named exactly **CHUD** and **JARVIS**. Chudvis
uses CHUD by default; use **Choose Voice Preset** to switch between those two account voices and
**Test Voice** to verify playback while controls are running. The sidebar also shows
microphone/request state, partial
transcripts, answers, edit targets, applied summaries, review actions, Undo, and Clear Memory.
Questions remain silent; successful file creation and code edits can produce a short ElevenLabs TTS
summary.

The bridge listens only on the configured loopback address. Camera frames, microphone audio,
source code, full transcripts, provider reasoning, API keys, and TTS bytes are not written to the
normal extension output channel. The separate local diagnostics stream records gesture/action
outcomes, exact recognized speech, bridge traffic, routing, and model request metadata. Exact model
prompts, workspace-tool data, and responses require the explicit **Capture exact model payloads**
toggle; credentials and session tokens are always redacted. Post-wake microphone audio is sent by
Python to ElevenLabs, while only the resolved source/context is sent by this extension to Backboard.

Use **Open Live Diagnostics** in the sidebar, **Chudvis: Show Diagnostics** in the Command Palette,
or **Chudvis: Follow Diagnostics in Terminal**. See `docs/diagnostics.md` in the repository for the
event schema, privacy behavior, and JSONL workflow.

See the repository's main README and `docs/ide-mode.md` for installation and usage.
