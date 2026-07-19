# Chudvis

> **Hands-free coding in VS Code — your eyes point, your hands commit, your voice does the rest.**

---

## Inspiration

Writing code is one of the last things you still can't do without your hands. Voice assistants can order you a pizza, but none of them can navigate a codebase.

Every developer tool assumes a mouse and a keyboard. That assumption quietly excludes people with limited mobility, anyone recovering from an RSI, and anyone whose hands are otherwise busy — and it's the hardest assumption to remove, because coding needs precision, not just commands.

The obvious fix is eye tracking, and on its own it fails. Gaze-only interfaces suffer the **"Midas touch" problem**: everything you look at gets clicked. Looking isn't choosing. In an editor, one wrong click costs you real work. We wanted to know if separating *where you're looking* from *what you're committing to* would be enough to make hands-free coding actually usable.

## What it does

Chudvis is a VS Code extension that turns a webcam and a microphone into a complete hands-free coding interface. It splits control across three modalities, each doing only what it's good at:

- **👁️ Gaze → where.** Your eyes move the cursor and select targets.
- **✋ Gesture → what.** A deliberate hand gesture commits the action. Gaze never acts alone.
- **🎤 Voice → intent.** Say "Chudvis" to wake it, then ask a question or request a code change.

A typical flow: look at a function, pinch with your navigator hand to select it, say *"Chudvis, refactor this to use async"*, and the proposed edit comes back for review. Thumbs-up with your editor hand applies it. Nothing irreversible happens without an explicit gesture, and every edit is undoable.

## How we built it

**Architecture** — A TypeScript VS Code extension supervising a native Python runtime, communicating over a token-authenticated loopback socket with a versioned JSON schema.

- **Gaze** — MediaPipe `FaceLandmarker` iris landmarks, rebuilt into a head-normalized orthonormal face frame so gaze survives head movement, then fit with SVD-projected ridge regression (plus an RBF kernel variant). Adaptive blink rejection off a rolling eye-aspect-ratio median, One-Euro filtering on the output.
- **Gestures** — MediaPipe `HandLandmarker` feeding a hold-gated state machine. Left and right hands get distinct navigator/editor roles so pointing and confirming never collide.
- **Wake word** — sherpa-onnx int8 Zipformer keyword spotting, running entirely on CPU. No audio leaves the machine until you actually say "Chudvis."
- **Voice I/O** — ElevenLabs realtime WebSocket STT with server-side VAD in, streaming TTS out. faster-whisper as a fully offline fallback.
- **Intelligence** — Backboard fronting Anthropic and Google behind one key: tool-capable Claude for edits, cheaper Gemini for questions, with server-persisted threads so context carries across conversations.
- **Safety** — Model edits are validated before they land (exact-match checks, character budgets, path policy), then surfaced in a git-backed review flow.

## Challenges we ran into

**Calibration drift was the one that nearly sank it.** Feeding full-strength features straight into regression meant a profile that worked at the start of a session was noticeably off twenty minutes later. Standardizing and SVD-projecting to a bounded set of components before fitting is what made calibration hold — and it's also what lets a profile converge from a few dozen samples instead of needing a per-user trained model.

**Midas touch is a design problem, not a tuning problem.** No amount of dwell-time tweaking fixed accidental activation. Requiring a separate modality to commit was the only thing that worked.

**Gesture recognition on raw pose is unusable.** Instantaneous matching fires constantly on incidental hand motion. Every gesture had to arm over a hold duration with visible 0–1 progress, plus a grace window so a momentary tracking dropout mid-pinch doesn't drop your drag.

**The WSL/Windows split cost us real hours.** The camera, screen geometry, and DPI awareness all live on the Windows host, but the repo lives in WSL — so calibrating with a plain Linux `uv run` silently produces a profile with the wrong screen geometry. We ended up making the extension own the entire runtime lifecycle so calibration and live control can't disagree.

**Wake words fail silently.** A spelling the KWS model can't tokenize just... never triggers, with no error. We validate every generated token against the model vocabulary at setup so it fails loudly instead.

## Accomplishments that we're proud of

- **It actually works for real coding**, not just a scripted demo — precise enough to select a specific function on a dense screen.
- **Gaze and gestures need zero cloud credentials.** The whole tracking stack runs locally.
- **The always-listening path never touches the network.** Wake-word spotting is fully on-device.
- **Ships as one `.vsix`** that provisions its own Python runtime via `uv` — no separate repo clone, no manual environment setup.
- **We took security seriously for a hackathon project**: keys in VS Code SecretStorage rather than workspace `.env` so project code can't read them, SHA-256-verified model assets, and a camera that never starts without an explicit user action and a first-run disclosure.
- **Every AI edit is reviewable and undoable.** We never let a model write to your files unsupervised.

## What we learned

- **Modality separation beats modality accuracy.** We spent early effort trying to make gaze smart enough to know when you meant it. Giving that job to a different body part solved it outright.
- **Feedback is what makes an interface learnable.** The 0–1 arming progress fill did more for usability than any threshold we tuned — users need to see intent accumulating.
- **Classical ML was the right call.** Ridge regression over a projected feature space beat anything we could have trained in a weekend, and calibrates in under a minute.
- **Privacy boundaries are architectural.** "Local until the wake word" had to be designed in from the start; it isn't something you can bolt on afterward.
- **Distribution is a feature.** Making the extension own the Python runtime eliminated an entire category of setup bugs and platform mismatches.

## What's next for Chudvis

- **Desktop mode beyond VS Code** — the gaze and gesture stack is already editor-agnostic; the OS-level pointer path needs polish.
- **More editors** — the bridge protocol is versioned and schema-defined specifically so JetBrains and Neovim adapters are feasible.
- **Calibration that improves during use**, learning from confirmed selections rather than requiring a recalibration pass.
- **A richer gesture vocabulary**, including scroll and zoom, without sacrificing the deliberate-commit guarantee.
- **Accessibility user testing** with the people this is actually built for — our biggest gap, and the thing that would most change the roadmap.
- **Latency work** on the wake-word-to-response path, which is where the experience still feels like waiting.

## Built With

`typescript` `python` `vscode-extension` `mediapipe` `opencv` `numpy` `sherpa-onnx` `onnx` `elevenlabs` `whisper` `anthropic` `claude` `google-gemini` `backboard` `pynput` `uv` `websockets` `machine-learning` `computer-vision` `accessibility`
