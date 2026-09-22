"""Inspect a smoke-test trace at a threshold. Never connects to Home Assistant."""
import argparse
import json
from pathlib import Path


def replay(path, threshold, margin):
    for line in path.read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        if event.get("type") != "probabilities":
            continue
        ranked = sorted(event["probabilities"].items(), key=lambda item: item[1], reverse=True)
        winner, score = ranked[0]
        second = ranked[1][1] if len(ranked) > 1 else 0
        if score >= threshold and score - second >= margin and score > second:
            print(json.dumps({"would_request": winner, "probability": score, "elapsed_ms": event["elapsed_ms"], "before_audio_end": not event["audio_ended"], "scored_text": event["text"]}, indent=2))
            return
    print("No action would meet this threshold and margin in this trace.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    parser.add_argument("--threshold", type=float, default=.95)
    parser.add_argument("--margin", type=float, default=.05)
    args = parser.parse_args()
    if not .5 <= args.threshold <= 1 or not 0 <= args.margin <= 1:
        parser.error("threshold must be 0.5–1 and margin 0–1")
    replay(args.trace, args.threshold, args.margin)
