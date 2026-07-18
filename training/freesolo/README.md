# Freesolo post-training: a local brain for voice commands

GazeMotion has three ways to turn a spoken sentence into a desktop action:

| Parser | Understands natural phrasing? | Offline? | Latency |
|---|---|---|---|
| Backboard LLM | yes | no | ~1–2 s per command |
| Rule grammar | no — exact phrasings only | yes | instant |
| **Freesolo-trained model** | **yes** | **yes** | **fast** |

For an accessibility tool this matters: users shouldn't need an internet
round-trip to say "bring up the calculator", and they shouldn't have to
memorize the exact phrase "open calculator" either. Post-training a small
model on [Freesolo](https://freesolo.co/) gives cloud-level understanding
that runs locally.

## The measurable gap

The eval set mixes *template* phrasings (what the rule grammar handles) with
*hard* natural phrasings (hand-labeled). The baseline:

```text
$ uv run python training/freesolo/evaluate.py --target rules

Intent accuracy for rule grammar:
  template  14/14  (100%)
  hard      0/9  (0%)
```

The rules cannot parse "make the page go down", "get me out of this tab", or
"i want to see hackthe6ix dot com". A model trained on `train.jsonl` (which
contains 20 more hard examples like these) learns both the strict format and
the natural variation.

## Workflow

1. Generate the dataset (chat-format JSONL):

   ```bash
   uv run python training/freesolo/generate_dataset.py
   ```

2. Point your Freesolo training package at `train.jsonl` / `eval.jsonl` and run
   SFT on a small instruct model. The task is strict JSON emission, so exact
   match against the assistant message works as a reward for an RL pass too.

3. Serve the trained model behind any OpenAI-compatible endpoint and measure
   the improvement over the baseline:

   ```bash
   uv run python training/freesolo/evaluate.py --target endpoint \
       --base-url http://127.0.0.1:8000/v1 --model gazemotion-intents
   ```

4. Switch GazeMotion's live agent over to it in the config:

   ```json
   "agent": {
     "provider": "openai-compatible",
     "openai_base_url": "http://127.0.0.1:8000/v1",
     "openai_model": "gazemotion-intents"
   }
   ```

   Set `FREESOLO_API_KEY` if the endpoint needs auth. Every voice command now
   runs through your own model with no cloud dependency.
