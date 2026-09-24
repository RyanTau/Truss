"""Read cumulative transcript lines from stdin and print staged LAYA results."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "truss_engine"))
from engine.request_eval import RequestEval


def main():
    from laya import Router

    evaluator = RequestEval(
        router=Router(preload=True),
        devices={"climate.dyson": "Dyson heater/fan", "light.room": "Room lights"},
        actions={
            "climate.dyson": {"turn_on": "Turn the Dyson on", "turn_off": "Turn the Dyson off",
                              "set_temperature_19": "Set the Dyson temperature to 19 degrees"},
            "light.room": {"turn_on": "Turn the lights on", "turn_off": "Turn the lights off"},
        },
    )
    print("Enter each full cumulative transcript on a new line; Ctrl+D (Windows: Ctrl+Z) ends. No actions are executed.", file=sys.stderr)
    for result in evaluator.eval_loop(line.rstrip("\r\n") for line in sys.stdin):
        print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
