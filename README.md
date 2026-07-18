# GazeMotion

GazeMotion is a local desktop-control prototype that uses webcam gaze estimation to position
the pointer, hand gestures to act, and speech for both dictation and natural-language
commands. Dictated speech runs through a voice command agent that can open apps and
websites, search the web, scroll, and press shortcuts; spoken feedback confirms every
action, and an optional wellness monitor watches for fatigue using contactless vitals.

The current MVP intentionally uses raw operating-system mouse and keyboard events. It can
therefore work outside a browser, but it does not yet understand whether a screen coordinate
contains a button or text field.

## Implemented controls

| Input | Action |
|---|---|
| Gaze | Move the desktop pointer |
| Quick thumb/index pinch | Click at the gaze position captured when the pinch began |
| Pinch and hold | Start a drag; move the hand to drag and release to drop |
| Open palm moved vertically | Scroll |
| Open palm held still | Pause or resume all actions |
| Thumbs-up held | Start dictation; repeat to run the transcript through the voice agent |

## Voice command agent

Anything you dictate is interpreted as either a command or plain text. Say
"open youtube dot com", "search for accessible input devices", "scroll down",
"select all", or "stop listening" and the matching desktop action runs; anything
else is typed into the focused field like regular dictation.

Three interchangeable parsers implement the same interface:

- **Backboard** (default): set `BACKBOARD_API_KEY` and transcripts are parsed by an LLM
  through the [Backboard.io](https://backboard.io) unified API. One Backboard thread is
  kept per session and Backboard memory is enabled, so context carries across commands
  and sessions.
- **Offline rules**: a regex grammar used automatically when no key is set or the
  network fails mid-demo. No cloud, no latency.
- **Local model**: any OpenAI-compatible endpoint (`agent.provider: "openai-compatible"`),
  intended for a [Freesolo](https://freesolo.co) post-trained intent model that understands
  natural phrasings ("bring up the calculator") offline. The rule grammar scores 0% on
  those; `training/freesolo/` has the dataset, the evaluation harness that proves the
  gap, and the workflow to close it.

## ElevenLabs voice: hear and speak

Set `ELEVENLABS_API_KEY` and ElevenLabs handles both sides of the conversation:

- **Speech to text (Scribe)**: when you dictate, the recording is transcribed by the
  ElevenLabs Scribe model instead of the small local Whisper model — noticeably more
  accurate for command phrases. Whisper remains the automatic offline fallback, and
  `voice.provider` can force either engine.
- **Text to speech**: GazeMotion speaks confirmations — "Opening github.com", "Paused",
  wellness suggestions — through the ElevenLabs TTS API. Audio arrives as raw PCM and
  plays through the existing sounddevice stack; repeated messages are deduplicated and
  playback never blocks the camera loop.

Without the key, dictation uses local Whisper and feedback is print-only.

## Wellness monitor (Presage)

Set `PRESAGE_API_KEY` and GazeMotion periodically records a short clip from the webcam
feed it is already processing and sends it to the
[Presage SmartSpectra Physiology API](https://physiology.presagetech.com) for contactless
pulse and breathing measurement. Readings are compared against your session baseline to
suggest breaks or breathing resets — long hands-free sessions are exactly where fatigue
creeps in. Clips are deleted immediately after upload and vitals are never persisted.
Set `wellness.auto_pause_on_alert` to pause input automatically when vitals run high.

Press `Esc` in the optional preview window, or `Ctrl+C` in the terminal, for an emergency stop.

## Setup

Python 3.10 or 3.11 is recommended.

```bash
uv sync --extra voice --extra dev
uv run gazemotion doctor
uv run gazemotion calibrate
uv run gazemotion run
```

Speech support downloads the configured Whisper model the first time it is used. To omit the
larger speech dependencies:

```bash
uv sync --extra dev
uv run gazemotion run --no-voice
```

MediaPipe face and hand model assets are also downloaded into the user cache on first use. An
optional tuning template is provided in `config.example.json`; pass a copied file with
`--config /path/to/config.json`.

On Linux, raw input libraries normally require an X11 session. Wayland compositors may block
synthetic global input. Start with `--dry-run --preview` if you are unsure:

```bash
uv run gazemotion run --dry-run --preview
```

## Commands

```text
gazemotion doctor                       Check dependencies, display, camera, calibration, and API keys
gazemotion calibrate [--camera 0]       Run nine-point gaze calibration
gazemotion test [--camera 0]            Safely inspect tracking, gaze, and gesture triggers
gazemotion run [--preview] [--dry-run]  Start desktop control
```

`run` also accepts `--no-agent` (type transcripts verbatim), `--no-speak`, and
`--no-wellness`. With `--dry-run`, voice commands print what they would do instead of
launching anything.

API keys are read from environment variables only and are never written to disk:

```text
BACKBOARD_API_KEY    LLM intent parsing (Backboard.io)
ELEVENLABS_API_KEY   Spoken feedback (ElevenLabs)
PRESAGE_API_KEY      Contactless vitals (Presage SmartSpectra)
```

## Tracking diagnostics

Run diagnostics before calibration or whenever gestures feel unreliable:

```bash
uv run gazemotion test
```

This mode never emits operating-system mouse or keyboard actions. Its dashboard shows:

- Live camera with eye/iris landmarks and the complete hand skeleton
- Whether the face and hand models are producing landmarks
- Raw iris features used by calibration
- Pinch ratio and its configured activation threshold
- Open-palm and thumbs-up classifier results
- Recent click, drag, scroll, pause, and dictation gesture events
- Loaded calibration metadata
- A mini screen containing the current calibrated gaze position

The camera panel preserves a 1280x720 source at native size on a 1920x1080 or larger display.
Unconfirmed hand candidates are drawn in gray and labeled with confirmation progress; only an
orange `ACTION READY` skeleton is sent to the gesture engine. Pinch arming and cancellation are
labeled as phases rather than actions.

It also prints completed gesture events to the terminal. The gaze screen is disabled when no
calibration exists, but camera and hand diagnostics continue to work.

Scrolling requires a confirmed open palm for a short arming period followed by accumulated,
directionally consistent movement. Small landmark jitter is discarded and scroll events are
rate-limited. Very short one-frame pinches are cancelled rather than clicked.

Calibration profiles contain only regression coefficients and screen/camera metadata. Camera
frames and microphone recordings are never persisted by default.

## Development

```bash
uv run pytest
uv run ruff check .
```

The core is structured around typed events and replaceable adapters. Future browser DOM and
native accessibility integrations can implement the same `InputAdapter` boundary without
changing gaze or gesture recognition.

## Current boundary

This release intentionally does not inspect the control under the pointer. Dictation therefore
starts with an explicit thumbs-up after the user has clicked a field. Browser DOM or native
accessibility adapters can later automate editable-field detection and target snapping.
