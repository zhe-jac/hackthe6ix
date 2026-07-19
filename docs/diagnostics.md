# Live diagnostics

Chudvis records a structured event stream for the real IDE runtime. Open it from the sidebar with
**Open Live Diagnostics**, or run **Chudvis: Show Diagnostics** from the Command Palette. The view
updates while controls run and can filter by category or arbitrary payload text, pause live
rendering, clear the session, open the normal diagnostic output, or reveal the underlying JSONL
file.

The stream separates recognition from execution. A typical gesture produces `gesture.committed`
followed by either `action.gesture.executed` or `action.gesture.ignored`, including the hand role,
controller state, mapped action, and rejection reason. Speech events include the exact partial and
committed transcript. Bridge events show every notification received from Python and every
notification sent back, with a `delivered` flag. Router, resolved-target, edit-validation,
application, and completion events share a request ID where one exists.

Backboard traffic records the endpoint, method, status, duration, and payload shape by default. To
see the exact prompts, selected source context, tool arguments/results, streamed events, and final
responses, enable **Capture exact model payloads** in the diagnostics view. This setting is off by
default because those payloads can contain workspace source and transcripts. API keys,
authorization fields, passwords, secrets, and bridge session tokens are redacted regardless of the
setting.

Use **Chudvis: Follow Diagnostics in Terminal** or the view's **Follow in Terminal** button for a
terminal stream. It follows the same per-extension-session JSONL file shown at the top of the view.
On Unix the equivalent manual command is:

```bash
tail -n 200 -f -- /path/shown/in/the/diagnostics/view
```

Each line is an independent JSON object:

```json
{
  "sequence": 42,
  "timestamp": "2026-07-19T18:22:31.412Z",
  "category": "action",
  "name": "gesture.executed",
  "data": {
    "gesture": "scroll",
    "role": "editor",
    "action": "editor.scroll",
    "controllerState": "tracking",
    "lines": 5
  }
}
```

The in-memory viewer retains the latest 1,000 events. The JSONL file retains the complete current
extension-host session until **Clear** is used; VS Code owns and eventually rotates the parent log
directory.
