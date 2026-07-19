# Chudvis

This extension owns the complete Chudvis IDE-mode lifecycle. It launches its packaged native Python
runtime for local gaze, two-hand gestures, “Chudvis” wake detection, and activated ElevenLabs
speech I/O. In-process extension services handle deterministic navigation, stream stateless
Backboard explanations, validate exact-text edit proposals, open native diffs for scope expansion,
and provide guarded Undo.

Use **Chudvis: Calibrate Gaze**, **Chudvis: Test Tracking Safely**, **Chudvis: Start Gaze, Gesture,
and Voice Controls**, and **Chudvis: Stop Gaze, Gesture, and Voice Controls**. Activation leaves the
runtime off until the toggle shortcut, status item, or an explicit Start command is used. A separate
terminal or `uv run` command is not required after the extension is installed.

Use `Ctrl+Alt+G` on Windows/Linux or `Cmd+Alt+G` on macOS to toggle all live controls. Clicking the
Chudvis status-bar item performs the same toggle. The sidebar includes synchronized **Start/Stop
Controls**, **Test Tracking**, and **Recalibrate Gaze** buttons, plus a visible guide to every gaze,
hand, voice, and keyboard action. Every guide entry explicitly labels its hand assignment; editor
defaults to the physical right hand, navigator defaults to the physical left hand, and the
pause/cancel hold accepts either hand.

Use **Chudvis: Configure Backboard API Key** to store the provider key in VS Code SecretStorage.
The sidebar shows microphone/request state, partial transcripts, answers, edit targets, applied
summaries, review actions, Undo, and Clear Memory. Basic navigation and questions remain silent;
only a successful code edit (or short edit failure) can produce an ElevenLabs TTS response.

The bridge listens only on the configured loopback address. Camera frames, microphone audio,
source code, full transcripts, provider reasoning, API keys, and TTS bytes are not written to the
extension output channel. Post-wake microphone audio is sent by Python to ElevenLabs, while only
the resolved source/context is sent by this extension to Backboard.

See the repository's main README and `docs/ide-mode.md` for installation and usage.
