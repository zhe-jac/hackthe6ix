# GazeMotion

GazeMotion is a local desktop-control prototype that uses webcam gaze estimation to position
the pointer, hand gestures to act, and optional offline speech recognition to enter text.

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
| Thumbs-up held | Start dictation; repeat to transcribe, type, and press Enter |

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
gazemotion doctor                       Check dependencies, display, camera, and calibration
gazemotion calibrate [--camera 0]       Run nine-point gaze calibration
gazemotion test [--camera 0]            Safely inspect tracking, gaze, and gesture triggers
gazemotion run [--preview] [--dry-run]  Start desktop control
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
