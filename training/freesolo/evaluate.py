"""Score an intent parser against the eval set.

Compares predictions to labels with exact-match on the normalized intent list,
reported separately for template phrasings (the rule grammar's home turf) and
hard natural phrasings (what post-training is for). Usage:

    uv run python training/freesolo/evaluate.py --target rules
    uv run python training/freesolo/evaluate.py --target endpoint \
        --base-url http://127.0.0.1:8000/v1 --model gazemotion-intents

The endpoint target works with anything OpenAI-compatible, e.g. a model
post-trained on Freesolo and served locally. A useful demo comparison is the
rules baseline (fast, offline, brittle) against the trained model (fast,
offline, general).
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict
from pathlib import Path

from generate_dataset import _clean  # noqa: E402 - sibling script import

from gazemotion.agent.intents import Intent
from gazemotion.agent.parser import (
    OpenAICompatibleIntentParser,
    ParserError,
    RuleBasedIntentParser,
)
from gazemotion.core.config import AgentSettings


def _normalize_intents(raw_intents: list[dict]) -> list[dict]:
    """Canonicalize intent dicts so label and prediction compare fairly."""
    return [_clean(asdict(Intent.from_dict(item))) for item in raw_intents]


def load_eval(path: Path) -> list[tuple[str, list[dict], str]]:
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            user = next(m["content"] for m in record["messages"] if m["role"] == "user")
            label = json.loads(
                next(m["content"] for m in record["messages"] if m["role"] == "assistant")
            )
            rows.append((user, _normalize_intents(label["intents"]), record["source"]))
    return rows


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--target", choices=("rules", "endpoint"), default="rules")
    cli.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    cli.add_argument("--model", default="gazemotion-intents")
    cli.add_argument("--eval-file", type=Path, default=Path(__file__).parent / "eval.jsonl")
    args = cli.parse_args()

    if args.target == "rules":
        parser = RuleBasedIntentParser()
        name = "rule grammar"
    else:
        settings = AgentSettings(openai_base_url=args.base_url, openai_model=args.model)
        api_key = os.environ.get(settings.openai_api_key_env, "unused")
        parser = OpenAICompatibleIntentParser(settings, api_key)
        name = f"{args.model} @ {args.base_url}"

    totals: dict[str, list[int]] = {"template": [0, 0], "hard": [0, 0]}
    failures: list[tuple[str, list[dict], list[dict]]] = []
    for spoken, label, source in load_eval(args.eval_file):
        try:
            predicted = _normalize_intents([asdict(i) for i in parser.parse(spoken)])
        except ParserError as exc:
            print(f"Request failed for {spoken!r}: {exc}")
            predicted = []
        totals[source][1] += 1
        if predicted == label:
            totals[source][0] += 1
        else:
            failures.append((spoken, label, predicted))

    print(f"\nIntent accuracy for {name}:")
    for source, (correct, count) in totals.items():
        if count:
            print(f"  {source:9s} {correct}/{count}  ({correct / count:.0%})")
    if failures:
        print("\nMisses:")
        for spoken, label, predicted in failures:
            print(f"  {spoken!r}\n    expected {label}\n    got      {predicted}")


if __name__ == "__main__":
    main()
