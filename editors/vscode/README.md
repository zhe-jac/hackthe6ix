# GazeMotion for VS Code

This extension is the semantic editor half of GazeMotion IDE mode. The Python runtime performs
local gaze, two-hand gesture, and speech recognition; this extension turns those intents into
editor scrolling, changed-file navigation, symbol selection, and confirmed agent requests.

The bridge listens only on the configured loopback address. Camera frames, microphone audio,
source code, and voice transcripts are not written to the extension output channel.

See the repository's main README and `docs/ide-mode.md` for installation and usage.
