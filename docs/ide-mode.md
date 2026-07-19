# Chudvis IDE mode

IDE mode separates physical perception from editor semantics. The extension launches and supervises
the packaged native Python runtime, which owns the camera, gaze calibration, hand identity, gesture
state machines, one microphone stream, local “Chudvis” detection, ElevenLabs realtime speech I/O,
and the local Whisper fallback. The VS Code extension owns document state, deterministic command
routing, Backboard requests, bounded edit validation, native diffs, Undo, and the Chudvis sidebar.

Extension activation is passive: it registers the UI and commands but does not start the bridge,
camera, microphone, or Python runtime. `Ctrl+Alt+G` on Windows/Linux (`Cmd+Alt+G` on macOS), the
sidebar **Start/Stop Controls** button, the clickable status item, and **Chudvis: Toggle Controls**
all control the same supervised IDE process. Calibration and tracking diagnostics are separate,
explicit modes and do not leave live controls running. The sidebar also exposes **Test Tracking**,
**Recalibrate Gaze**, and a persistent action guide.

```text
camera + one microphone stream
        |
        v
Chudvis Python runtime
  MediaPipeTracker(max_hands=2)
  HandGestureRouter
  IdeInteractionController
  SherpaWakeWordDetector -> ElevenLabs realtime STT/TTS
        |
        | JSON-RPC notifications over loopback
        v
VS Code extension
  semantic selection
  deterministic voice router
  Backboard provider + read-only workspace tools
  exact-text edit validator + native diff/Undo
  Chudvis webview view
```

## Compatibility boundary

`chudvis run` still creates the original one-hand `InteractionController` and emits raw desktop
input. `chudvis ide` creates a two-hand tracker, one `GestureEngine` per role, an
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

`left` and `right` mean the user's physical hands, not the side of the mirrored preview where a hand
appears. Chudvis converts MediaPipe's mirrored-view labels at the perception boundary before it
assigns either role. Set different values for `navigator_hand` and `editor_hand` to swap physical
roles, and use `chudvis test --ide` to confirm the labels before enabling actions.

## Cloud setup and disclosure

The packaged extension runtime installs the voice extra in its isolated environment. Configure
Backboard and ElevenLabs from **AI and voice setup** in the sidebar or the matching Command Palette
commands. Both credentials stay in VS Code SecretStorage. The extension passes the saved
ElevenLabs key only to its supervised native process; an existing `ELEVENLABS_API_KEY` in the native
VS Code host environment is also accepted. Workspace `.env` files are not loaded.

On first bridge start, the extension presents a native modal disclosure that post-activation audio
goes to ElevenLabs and resolved source/context goes to Backboard. Declining leaves the bridge
stopped. The sidebar reports whether each credential is saved or inherited from the host
environment without exposing its value.

The default voice timings and limits are represented in `config.example.json`. Set
`voice.wake_word_enabled` to `false` to use only the local Whisper gesture fallback. The wake model
is pinned to `sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01`, licensed Apache-2.0. Downloads
use an exact archive checksum, per-asset checksums, a cache, and traversal/link-safe extraction.

## Selection flow

VS Code extensions can observe document selections but cannot reliably convert arbitrary desktop
coordinates into document positions. Chudvis uses a hybrid flow:

1. Gaze moves the OS pointer.
2. Editor-hand pinch start locks the latest fresh gaze sample and arms the extension.
3. Pinch release clicks the locked point.
4. The extension accepts only the resulting mouse selection event within the arm timeout.
5. It selects the smallest enclosing document symbol, or the current line when symbols are absent.
6. A decoration makes the attached context visible before dictation is submitted.

Keyboard and command selection events cannot satisfy an armed gaze selection. Stale arms expire and
document-version changes invalidate stored context.

## Voice pipeline and request state

```text
microphone -> local Sherpa “Chudvis” -> ElevenLabs WebSocket -> VAD commit -> router
                 no network audio       partial transcript              |
                                                                       +-> local command
                                                                       +-> question
                                                                       +-> bounded edit
```

One continuously owned `sounddevice.InputStream` feeds bounded worker queues. The callback never
performs network or model work. While ready, samples go only to local Sherpa ONNX; no audio is sent
over the network before detection. After detection, post-wake samples accumulate while the
ElevenLabs WebSocket connects, then stream as 16 kHz mono PCM in 100 ms chunks to
`scribe_v2_realtime`. Server VAD commits after 1.2 seconds of silence. No-speech and maximum-request
timeouts default to 8 and 30 seconds. Wake detection pauses during request processing and TTS, then
re-arms automatically.

Every request requires a fresh wake word. “Cancel,” “never mind,” open palm, the sidebar Cancel
button, shutdown, and Backboard cancellation all return safely to Ready. If wake streaming cannot
start, editor-hand thumbs-up retains the existing local Whisper preview/confirmation flow.

The deterministic router handles `open file`, `go to symbol`, `show references`, Undo, and Cancel
without Backboard or TTS. `explain`, `analyze`, `why`, `what`, and `how` are questions. Explicit
`change`, `fix`, `add`, `remove`, `rename`, and `refactor` verbs are edits. Question phrasing wins
over mutation words, and anything ambiguous is a question.

## Backboard context and memory

Configure the API key with **Chudvis: Configure Backboard API Key**. It is stored in VS Code
SecretStorage, never settings or logs. On setup, Chudvis validates the configured models against
Backboard's Models API. The defaults are `anthropic / claude-opus-4-7-20250501` for edits and
`google / gemini-3.5-flash` for questions. If a default is unavailable, Chudvis requires a Quick
Pick selection; edit choices must support tools and at least 32k context.

The extension creates one assistant and persistent editing thread per workspace. Editing uses
`memory="Auto"`, with a memory prompt that permits only durable project decisions and concise
applied-edit summaries. Questions use a temporary thread with memory off, stream into the sidebar,
and delete that thread afterward. **Clear Editing Memory** deletes the remote thread and assistant
and clears their workspace IDs.

The initial request contains only the resolved source, necessary imports, relative path, language,
and document version. Target priority is gesture semantic selection, manual selection, an explicitly
named active-document symbol, the smallest cursor-enclosing symbol, then the active file. Backboard
can inspect more context only through bounded `read_workspace_file`, `find_workspace_symbol`, and
`list_workspace_files` tools. It has no shell, terminal, test, create, delete, or rename tool.

## Edit validation and review

Backboard proposes exact existing `originalText` → `replacementText` operations. Chudvis rejects
empty or non-unique originals, stale versions, overlaps, paths outside workspace roots, generated or
dependency folders, secrets, binaries, oversized files/responses, and changes over the configured
limit. At most three files can be confirmed in one expanded request. All accepted replacements are
applied together with one `WorkspaceEdit`.

Operations wholly inside the resolved target auto-apply. If any operation leaves that boundary—even
for another function in the same file—the extension creates read-only original/proposed snapshots,
opens a native VS Code diff, and waits for Apply/thumbs-up. Cancel/open palm rejects the whole
proposal. Navigator-hand vertical gestures cycle proposal/applied files and hunks; editor-hand
vertical gestures scroll the active diff.

After application, the extension verifies the actual text, submits the tool result, and asks for one
plain sentence no longer than 160 characters. That sentence (or a deterministic fallback) is shown,
sent to Python, and streamed through ElevenLabs TTS exactly once. TTS failure never rolls back code.
Undo is available only while every affected document version and applied snapshot still match; it
refuses rather than overwriting later work.

## Legacy review capture

The extension retains the original change-capture navigator for explicitly configured legacy VS
Code CLI requests. VS Code document and workspace file events become file/range entries; Git and
dirty-editor files provide a fallback when no entries were captured.

Generated directories such as `.git`, `.venv`, `node_modules`, and `dist` are excluded. Existing
dirty files are not treated as part of a newly submitted request unless they change after the
session begins.

## Bridge protocol and safety

The extension listens only on a loopback host. The first message must be `bridge.hello` with
protocol version 1 and the configured session token. Each side enforces a message-size limit.
Malformed messages or an invalid token close the connection. The Python transport uses a bounded
queue, does not block the camera loop, reconnects automatically, and discards queued commands when
an editor connection is lost so stale gestures cannot execute later.

The preferred address is `127.0.0.1:8765`. Passive activation does not attempt to bind it. On an
explicit Start, the extension falls back to a private ephemeral loopback port when necessary and
passes that actual port and session token directly to its runtime process. Multiple VS Code windows
therefore do not require independently edited config files or a manually chosen port.

The protocol envelope is defined in `protocol/ide-v1.schema.json`. Current Python-to-extension
methods are:

- `review.navigate`
- `editor.scroll`
- `selection.arm` and `selection.cancel`
- `request.preview`, `request.submit`, and `request.cancel`
- `control.pause`
- `voice.state`, `voice.partial`, and `voice.request`
- `edit.approve` and `edit.cancel`

Extension-to-Python methods are `voice.cancel`, `voice.complete`, and
`edit.approvalRequested`; `bridge.status` remains for general status. Both sides validate enums,
IDs, string lengths, array counts, and total message size, ignore stale request IDs, and make
completion/cancellation idempotent.

In a Remote WSL window, install with `./scripts/install-vscode-extension.sh`. The extension runs in
the Windows/UI host, launches its packaged runtime through `chudvis-windows.ps1`, and keeps the
loopback bridge on the same host as the Windows-native camera and pointer runtime.
WSL workspace URIs are translated to `\\wsl.localhost\<distribution>\...` only when passing selected
file context to the Windows VS Code CLI; shell command strings are never constructed.

Do not run IDE mode with plain `uv run` in WSL. Linux `pynput` cannot place the pointer in the native
Windows editor. Use the extension's Start, Stop, Calibrate, and Test Tracking commands; the standalone
Windows launcher remains available for desktop-mode development and troubleshooting.

## Development checks

From the repository root:

```bash
uv sync --extra dev
uv run chudvis doctor --ide --skip-camera
uv run pytest
uv run ruff check .
uv run mypy

cd editors/vscode
npm ci
npm run verify
npm run package
```

Python tests use recording adapters, fake audio streams/transports, and synthetic landmarks.
Extension tests exercise routing, proposal/path validation, SSE parsing, bridge authentication, and
protocol rejection without requiring a camera or running VS Code.
