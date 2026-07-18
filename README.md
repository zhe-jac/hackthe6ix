# GazeMotion — Zero-Contact Desktop Control

A local, hands-free computer-control system that uses a **standard webcam** to drive the whole
desktop: your **eyes aim** the pointer, your **hand gestures act**, and your **voice dictates and
commands**. No proprietary eye-tracker, no wearables — just the camera already in your laptop.

We don't click whatever you look at. GazeMotion splits **selection** (where you look) from
**action** (what you gesture), so it never suffers the gaze "Midas touch" of accidental clicks.

Hackathon build (HackThe6ix). Integrations: **Backboard.io** (LLM intent) · **ElevenLabs**
(speech + voice) · **Presage** (contactless vitals) · **Freesolo** (offline intent model).

## Docs

- **[docs/product_brief.md](docs/product_brief.md)** — start here: system map, module-by-module
  architecture, key functions, and the venture pitch.
- **[PRD.md](PRD.md)** — product requirements and scope.
- **[training/freesolo/](training/freesolo/)** — dataset, evaluation harness, and workflow for the
  offline Freesolo intent model that closes the gap the rule parser can't.

## Run

Python 3.10 or 3.11 recommended.

```bash
uv sync --extra voice --extra dev   # or --extra dev alone, then run --no-voice
uv run gazemotion doctor            # check camera, display, calibration, API keys
uv run gazemotion calibrate         # nine-point gaze calibration
uv run gazemotion run --preview     # start hands-free control (add --dry-run to test safely)
```

`uv run gazemotion test` opens a diagnostics dashboard that shows tracking, gaze, and gesture
triggers **without emitting any real mouse or keyboard actions**. Press `Esc` in the preview or
`Ctrl+C` in the terminal for an emergency stop.

### Controls

| Input | Action |
|---|---|
| Gaze | Move the pointer |
| Quick thumb/index pinch | Click at the gaze position captured when the pinch began |
| Pinch and hold | Drag; release to drop |
| Open palm moved vertically | Scroll |
| Open palm held still | Pause / resume all actions |
| Thumbs-up held | Start dictation; repeat to run the transcript through the voice agent |

### API keys

Read from environment variables only, never written to disk. All are optional — GazeMotion
degrades gracefully to offline behavior without them.

```text
BACKBOARD_API_KEY    LLM intent parsing (Backboard.io)
ELEVENLABS_API_KEY   Speech-to-text (Scribe) + spoken feedback (ElevenLabs)
PRESAGE_API_KEY      Contactless pulse/respiration (Presage SmartSpectra)
```

## Current state

The **perception and control core is real**: webcam iris/face/hand tracking (MediaPipe),
ridge-regression gaze calibration with adaptive smoothing, the gesture engine, and raw
OS-level mouse/keyboard dispatch (pynput) all work end-to-end on unmodified desktop apps.

The voice agent routes dictation through three interchangeable parsers on the same interface —
**Backboard** LLM (default, with cross-command thread memory), an **offline regex grammar**
(automatic fallback when no key is set or the network drops), and a **local Freesolo** model
(OpenAI-compatible endpoint for natural offline phrasings the rules can't parse). ElevenLabs
handles both Scribe transcription and spoken confirmations, with local Whisper as the offline
fallback. The Presage wellness monitor samples short clips for contactless vitals and can
auto-pause on fatigue; clips are deleted after upload and vitals are never persisted.

**Deliberate boundary:** this MVP works outside the browser but does not yet inspect the control
under the pointer — it doesn't know a coordinate is a button or a text field. Dictation therefore
starts with an explicit thumbs-up after you've clicked a field. The core is built around typed
events and replaceable adapters, so a browser-DOM or native-accessibility `InputAdapter` can add
target snapping later without touching gaze or gesture recognition.

## Development

```bash
uv run pytest
uv run ruff check .
```
