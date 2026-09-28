"""Inspect highest-probability selection in a smoke-test trace. Never connects to Home Assistant."""
import argparse
import json
from pathlib import Path


def replay(path):
    for line in path.read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        if event.get("type") != "probabilities":
            continue
        ranked = sorted(event["probabilities"].items(), key=lambda item: item[1], reverse=True)
        if not ranked or (event.get("score_scope") == "staged_minimum" and event.get("decision") is None):
            continue
        winner, score = ranked[0]
        if score > 0:
            print(json.dumps({"would_request": winner, "probability": score, "elapsed_ms": event["elapsed_ms"], "before_audio_end": not event["audio_ended"], "scored_text": event["text"]}, indent=2))
            return
    print("No action was selected in this trace.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    args = parser.parse_args()
    replay(args.trace)
