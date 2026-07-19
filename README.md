<p align="center">
  <img src="docs/assets/chudvis-logo.png" width="220" alt="Chudvis logo">
</p>

# Chudvis

Chudvis is a hands-free VS Code extension. It uses webcam-based gaze tracking and hand gestures to
select and navigate code, plus an optional local “Chudvis” wake word for voice commands, questions,
and guarded code edits.

The extension packages and manages the native Python tracking runtime itself. You do not need to
start a separate Python process or run any of the repository's platform scripts.

## Requirements

- VS Code 1.95 or newer
- [`uv`](https://docs.astral.sh/uv/) on the same host as VS Code
- A webcam
- A microphone for voice features
- Node.js and npm when building the extension from source

Backboard is used for questions and code edits. ElevenLabs is used for realtime speech after the
wake word. Gaze, gestures, calibration, and tracking diagnostics do not require either service.

## Install from source

Build and install the extension from the repository root:

```bash
cd editors/vscode
npm install
npm run package
code --install-extension ./chudvis-vscode.vsix --force
```

Reload VS Code after installation. If `code` is unavailable, install the generated
`editors/vscode/chudvis-vscode.vsix` through VS Code's **Extensions: Install from VSIX...** command.

## Set up Chudvis

Open the Chudvis view from the Activity Bar, then:

1. Choose **Set Backboard Key** to enable questions and code edits.
2. Choose **Set ElevenLabs Key** to enable wake-word speech input.
3. Choose **Recalibrate Gaze** and follow the on-screen targets.
4. Choose **Test Tracking** to check gaze and gesture recognition without emitting mouse or
   keyboard input.
5. Choose **Start Controls** or press `Ctrl+Alt+G` (`Cmd+Alt+G` on macOS).

Use the same button or shortcut to stop Chudvis. Installing or opening the extension does not start
the camera, microphone, or controls automatically.

Keys entered in the sidebar are stored in VS Code SecretStorage. An `ELEVENLABS_API_KEY` in the VS
Code host environment is also supported. Workspace `.env` files are not loaded.

## Controls

The physical right hand is the editor hand by default, and the physical left hand is the navigator
hand.

| Input | Action |
| --- | --- |
| Gaze | Move the pointer |
| Editor-hand quick pinch | Click the gaze target and select its enclosing symbol or current line |
| Editor-hand vertical open-palm movement | Scroll the editor or diff |
| Navigator-hand vertical open-palm movement | Move between captured changes |
| “Chudvis,” followed by a request | Navigate, ask a question, or request an edit |
| Editor-hand thumbs-up | Approve a pending edit or use the local dictation fallback |
| Either-hand open-palm hold | Cancel an active request, otherwise pause or resume controls |

Example voice requests:

```text
Chudvis, open the configuration file
Chudvis, create a new markdown file named notes
Chudvis, go to the startControls symbol
Chudvis, show references
Chudvis, explain what this function does
Chudvis, rename this parameter to sessionToken
Chudvis, undo that
```

File creation, file and symbol navigation, references, Undo, and Cancel are handled locally.
Questions and explicit edit requests use Backboard. An edit contained within the selected target can
be applied directly; a broader edit opens a VS Code diff and waits for approval. Create-file
requests never overwrite an existing file.

## Privacy

- Camera frames are processed locally and are not saved by Chudvis.
- Wake-word detection runs locally.
- After wake activation, microphone audio is sent to ElevenLabs for realtime transcription.
- Questions and edits send the resolved source context to Backboard.
- Calibration profiles contain model and screen/camera metadata, not camera frames.

## Development

The extension includes a TypeScript VS Code host and a Python perception runtime. Run their checks
with:

```bash
uv sync --extra voice --extra dev
uv run pytest
uv run ruff check .
uv run mypy

cd editors/vscode
npm install
npm run verify
```

Package a new VSIX with:

```bash
cd editors/vscode
npm run package
```

## Attribution

Head-normalized gaze feature selection and pose normalization are adapted from
[EyeTrax](https://github.com/ck-zhang/EyeTrax) under its MIT license. The license notice is included
with the gaze module.
