# GazeMotion IDE mode

IDE mode separates physical perception from editor semantics. The Python runtime owns the camera,
gaze calibration, hand identity, gesture state machines, microphone, and local transcription. The
VS Code extension owns document state, scrolling, selection, change review, request presentation,
and coding-agent dispatch.

```text
camera + microphone
        |
        v
GazeMotion Python runtime
  MediaPipeTracker(max_hands=2)
  HandGestureRouter
  IdeInteractionController
        |
        | JSON-RPC notifications over loopback
        v
VS Code extension
  semantic selection
  review navigator
  request coordinator
  VS Code CLI agent provider
```

## Compatibility boundary

`gazemotion run` still creates the original one-hand `InteractionController` and emits raw desktop
input. `gazemotion ide` creates a two-hand tracker, one `GestureEngine` per role, an
`IdeInteractionController`, and a local bridge. IDE-specific actions never enter `GestureEngine`,
which remains a pure recognizer.

Old configuration files remain valid because the `ide` object is additive. The default mapping is:

```json
{
  "ide": {
    "navigator_hand": "left",
    "editor_hand": "right",
    "host": "127.0.0.1",
    "port": 8765,
    "session_token": ""
  }
}
```

Set different values for `navigator_hand` and `editor_hand` to swap roles. Mirrored camera input is
the default and matches MediaPipe's handedness convention. Use `gazemotion test --ide` to confirm
the labels before enabling actions.

## Selection flow

VS Code extensions can observe document selections but cannot reliably convert arbitrary desktop
coordinates into document positions. GazeMotion uses a hybrid flow:

1. Gaze moves the OS pointer.
2. Editor-hand pinch start locks the latest fresh gaze sample and arms the extension.
3. Pinch release clicks the locked point.
4. The extension accepts only the resulting mouse selection event within the arm timeout.
5. It selects the smallest enclosing document symbol, or the current line when symbols are absent.
6. A decoration makes the attached context visible before dictation is submitted.

Keyboard and command selection events cannot satisfy an armed gaze selection. Stale arms expire and
document-version changes invalidate stored context.

## Voice request state

```text
tracking -> dictating -> transcribing -> request pending
                                            |       |
                                     thumbs-up   open palm
                                            |       |
                                      submitted  cancelled
```

The Python service transcribes locally and sends only the completed text to VS Code. The extension
shows a preview, but does not log the transcript. A second thumbs-up is required before dispatch.
The first provider invokes the configured VS Code CLI executable with structured arguments, agent
mode, the selected file, and a prompt containing the selected range. It never constructs a shell
command string.

## Review capture

The extension starts a new review session immediately before agent dispatch. VS Code document and
workspace file events are recorded as file/range entries. Navigator-hand movements walk those
entries in both directions. If a session has not captured any entries, current Git and dirty-editor
files provide a fallback review list.

Generated directories such as `.git`, `.venv`, `node_modules`, and `dist` are excluded. Existing
dirty files are not treated as part of a newly submitted request unless they change after the
session begins.

## Bridge protocol and safety

The extension listens only on a loopback host. The first message must be `bridge.hello` with
protocol version 1 and the configured session token. Each side enforces a message-size limit.
Malformed messages or an invalid token close the connection. The Python transport uses a bounded
queue, does not block the camera loop, reconnects automatically, and discards queued commands when
an editor connection is lost so stale gestures cannot execute later.

The protocol envelope is defined in `protocol/ide-v1.schema.json`. Current Python-to-extension
methods are:

- `review.navigate`
- `editor.scroll`
- `selection.arm` and `selection.cancel`
- `request.preview`, `request.submit`, and `request.cancel`
- `control.pause`

The extension reports user-facing state back through `bridge.status`.

In a Remote WSL window, install with `./scripts/install-vscode-extension.sh`. The extension runs in
the Windows/UI host so its loopback bridge matches the Windows-native camera and pointer runtime.
WSL workspace URIs are translated to `\\wsl.localhost\<distribution>\...` only when passing selected
file context to the Windows VS Code CLI; shell command strings are never constructed.

Run IDE mode from WSL through `./scripts/gazemotion-windows.sh ide --preview`, not through the Linux
virtual environment. Linux `pynput` cannot place the pointer in the native Windows editor, and the
Windows launcher keeps the camera runtime on the same host as the extension bridge.

## Development checks

From the repository root:

```bash
uv sync --extra dev
uv run gazemotion doctor --ide --skip-camera
uv run pytest
uv run ruff check .
uv run mypy

cd editors/vscode
npm ci
npm run verify
npm run package
```

Python tests use recording adapters and synthetic landmarks. Extension tests exercise protocol
validation, authentication, dispatch, and rejection without requiring a camera or running VS Code.
