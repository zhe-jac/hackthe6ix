<p align="center">
  <img src="docs/assets/chudvis-logo.png" width="220" alt="Chudvis logo">
</p>

# Chudvis

Chudvis is a multimodal control prototype that uses webcam gaze estimation to position the
pointer, hand gestures to act, and voice for text and coding requests. It supports both raw desktop
control and Chudvis IDE mode, a semantic two-hand VS Code voice assistant. Desktop dictation stays
offline; Chudvis detects its wake word locally, then uses configured cloud services for activated
requests.

The current MVP intentionally uses raw operating-system mouse and keyboard events. It can
therefore work outside a browser, but it does not yet understand whether a screen coordinate
contains a button or text field. IDE mode adds a local VS Code extension that understands files,
review changes, editor scrolling, selections, and coding-agent requests.

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

### IDE controls

| Input | IDE action |
|---|---|
| Gaze | Move the pointer toward a code target |
| Editor-hand quick pinch | Click the locked gaze target and select its enclosing symbol |
| Editor-hand open-palm movement | Scroll within the active editor |
| Navigator-hand open-palm movement | Move to the previous or next captured change |
| Say “Chudvis,” then speak | Start one realtime navigation, question, or code-edit request |
| Editor-hand thumbs-up | Approve an expanded edit, or use local Whisper when wake streaming is unavailable |
| Open palm held while a request is pending | Cancel the request |
| Open palm held otherwise | Pause or resume IDE control |

Hand roles are configurable and default to the user's physical left hand for navigation and
physical right hand for editing. The labels do not refer to which side of the mirrored preview a
hand appears on; Chudvis normalizes the detector's mirrored-view labels before assigning roles.

## Setup

Python 3.10 through 3.12 is supported.

```bash
uv sync --extra voice --extra dev
uv run chudvis doctor
uv run chudvis calibrate
uv run chudvis run
```

Voice support downloads the configured Whisper fallback and the pinned Apache-2.0 Sherpa ONNX
keyword model the first time each is used. The wake-model archive and runtime assets are verified
against pinned SHA-256 checksums. To omit the larger speech dependencies:

```bash
uv sync --extra dev
uv run chudvis run --no-voice
```

MediaPipe face and hand model assets are also downloaded into the user cache on first use. An
optional tuning template is provided in `config.example.json`; pass a copied file with
`--config /path/to/config.json`.

Gaze calibration uses a dense 5x5 target grid, balanced per-target samples, robust outlier and
blink rejection, and a separate nine-target validation pass. It compares regularized linear and
nonlinear gaze mappings and saves the simpler model unless the nonlinear mapping produces a
meaningful validation improvement. Runtime motion is stabilized with time-aware low-lag
filtering. Calibration profiles are model versioned; rerun `chudvis calibrate` when prompted.

On Linux, raw input libraries normally require an X11 session. Wayland compositors may block
synthetic global input. Start with `--dry-run --preview` if you are unsure:

```bash
uv run chudvis run --dry-run --preview
```

## VS Code IDE mode

Build, test, package, and install the included extension:

```bash
./scripts/install-vscode-extension.sh
```

When run from WSL, the installer deliberately uses the Windows VS Code CLI. Running
`code --install-extension` directly inside a WSL terminal targets the remote extension host and
will reject this UI-side extension. Reload the VS Code window after installation.

Open the target workspace in VS Code, calibrate Chudvis if needed, and then run:

```bash
uv sync --extra voice --extra dev
uv run chudvis test --ide
uv run chudvis ide --preview
```

Before starting IDE mode, expose an ElevenLabs key to the Python process and configure Backboard
from **Chudvis: Configure Backboard API Key** in the VS Code Command Palette. The Backboard key is
stored only in VS Code SecretStorage.

```bash
export ELEVENLABS_API_KEY="..."
```

For Windows-native execution, define `ELEVENLABS_API_KEY` in the Windows environment (or launch
from a PowerShell session where it is set). If the ElevenLabs key, wake dependencies, or microphone
are unavailable, IDE mode retains the confirmed thumbs-up/local-Whisper request flow.

From WSL, run the same flow through Windows-native Python so the webcam, pointer, extension bridge,
and VS Code UI share the Windows host:

```bash
./scripts/chudvis-windows.sh doctor --ide --skip-camera
./scripts/chudvis-windows.sh test --ide
./scripts/chudvis-windows.sh ide --preview
```

The extension starts its bridge on `127.0.0.1:8765`; the Python process reconnects automatically.
For a shared secret, set the same non-empty value in `ide.session_token` in the Chudvis JSON
configuration and `chudvis.bridge.sessionToken` in VS Code settings.

Chudvis handles file/symbol navigation locally. Questions stream from Backboard into the sidebar
without memory or speech. Explicit code edits use exact-text proposals and auto-apply only inside
the resolved selection/symbol; any scope expansion opens a native diff and waits for Apply or a
thumbs-up. Successful edits get a guarded Undo and one short ElevenLabs spoken summary. The old VS
Code CLI agent can be selected explicitly as `chudvis.provider = legacy-vscode-cli` for confirmed
local-Whisper fallback requests; it is not the default.

See [docs/ide-mode.md](docs/ide-mode.md) for architecture, state transitions, configuration, and
failure behavior.

### Run the Windows-native app from WSL

WSLg can display Linux windows but Linux `pynput` events do not control native Windows apps.
From WSL, use the included launcher to run the same source tree with Windows-native Python:

```bash
./scripts/chudvis-windows.sh doctor --skip-camera
./scripts/chudvis-windows.sh calibrate --camera 0
./scripts/chudvis-windows.sh run --preview --no-voice
./scripts/chudvis-windows.sh ide --preview
```

The launcher forwards any additional Chudvis arguments. It uses Windows `uv`, Python 3.12,
and a separate virtual environment under `%LOCALAPPDATA%\Chudvis`, so the Linux `.venv` is
left untouched. If Windows `uv` is missing, install it once from PowerShell with
`winget install --id astral-sh.uv -e`.

## Commands

```text
chudvis doctor [--ide]               Check runtime hardware and optionally the VS Code bridge
chudvis calibrate [--grid-size 5|7]  Run dense gaze calibration and validation
chudvis test [--camera 0]            Safely inspect tracking, gaze, and gesture triggers
chudvis run [--preview] [--dry-run]  Start desktop control
chudvis ide [--preview] [--dry-run]  Start semantic two-hand VS Code control
```

## Tracking diagnostics

Run diagnostics before calibration or whenever gestures feel unreliable:

```bash
uv run chudvis test
```

This mode never emits operating-system mouse or keyboard actions. Its dashboard shows:

- Live camera with eye/iris landmarks and the complete hand skeleton
- Whether the face and hand models are producing landmarks
- Head-normalized gaze readiness, feature count, blink state, and eye openness
- Pinch ratio and its configured activation threshold
- Open-palm and thumbs-up classifier results
- Recent click, drag, scroll, pause, and dictation gesture events
- Loaded calibration metadata
- Calibration model and held-out median/p95 error
- A mini screen containing the current calibrated gaze position
- A full-dashboard gaze reticle, enabled by default and toggled with `G`
- Practice cards with live hold progress and persistent completion markers for every gesture

The camera panel preserves a 1280x720 source at native size on a 1920x1080 or larger display.
Unconfirmed hand candidates are drawn in gray and labeled with confirmation progress; only an
orange `ACTION READY` skeleton is sent to the gesture engine. Pinch arming and cancellation are
labeled as phases rather than actions.

It also prints completed gesture events to the terminal. The gaze screen is disabled when no
calibration exists, but camera and hand diagnostics continue to work.

Scrolling requires a confirmed open palm for a short arming period followed by accumulated,
directionally consistent movement. Small landmark jitter is discarded and scroll events are
rate-limited. Very short one-frame pinches are cancelled rather than clicked. Active drags
survive brief hand-tracking flicker; uncommitted pinches use a shorter grace window and releases
that occur while the hand is missing are cancelled instead of clicked. Pause and dictation hold
timers restart after tracking loss.

Calibration profiles contain only feature normalization statistics, regression coefficients, and
screen/camera metadata. Camera frames and microphone recordings are never persisted by default.

The head-normalized gaze feature selection and pose normalization are adapted from
[EyeTrax](https://github.com/ck-zhang/EyeTrax) under its MIT license; the license notice is shipped
with the gaze module.

## Development

```bash
uv run pytest
uv run ruff check .
uv run mypy
cd editors/vscode && npm run verify
```

The core is structured around typed events and replaceable adapters. The VS Code integration uses
an independent IDE controller and adapter so the desktop controller remains backward compatible.
Future editor, browser DOM, and native accessibility integrations can reuse the same perception
and gesture recognition layers.

## Current boundary

Desktop mode intentionally does not inspect the control under the pointer. IDE mode understands
text editors and document symbols, but still uses the gaze-controlled OS pointer for the initial
screen-to-document hit because VS Code does not expose arbitrary desktop-coordinate hit testing.
