"""Real-model selection regression probe; never connects to HA or calls devices."""
import argparse
import json
from pathlib import Path
import sys
import time
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "truss_engine"))
from engine.models import LocalModels


def candidates():
    return [
        {"id": f"light.{entity}:{operation}", "entity_id": f"light.{entity}",
         "name": name, "label": f"Turn {operation} {name}", "aliases": aliases, "area": ""}
        for entity, name, aliases in (
            ("ball_lamp", "Ball lamp", ["Turkish lamp"]),
            ("dinning_room_tall_lamp", "Dining room tall lamp", ["Tall lamp"]),
            ("colour_light", "Colour light", []),
        ) for operation in ("on", "off")
    ]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio-dir", type=Path, help="Optional directory with lamp-0.wav through lamp-5.wav: tall/Turkish/colour, on then off, mono 16k PCM16")
    args = parser.parse_args()
    models = LocalModels({"bundled_stt": bool(args.audio_dir), "threads": 4})
    models.load()
    for text in ("Turn", "Turn on", "Turn on the", "Turn on the tall", "Turn on the tall lamp", "Turn the tall lamp on", "THUNDER TALL LAMP ON", "Turn off the tall lamp",
                 "Turn on the Turkish lamp", "Turn off the Turkish lamp", "Turn off the colour light",
                 "TURN OFF THE COLORED LION", "Turn on", "Do not turn on the tall lamp",
                 "turksih lamp off please", "could you put the tal lamp on please",
                 "colored light off", "tall lamp on please", "Is the tall lamp on?"):
        started = time.perf_counter()
        scores = models.score(text, candidates())
        print(json.dumps({"text": text, "scores": scores, "ms": round((time.perf_counter() - started)*1000)}), flush=True)
    if args.audio_dir:
        for index in range(6):
            with wave.open(str(args.audio_dir / f"lamp-{index}.wav"), "rb") as wav:
                if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, 16000):
                    raise ValueError("Expected mono 16 kHz PCM16 WAV")
                audio = wav.readframes(wav.getnframes())
            stream = models.create_stream(candidates())
            started = time.perf_counter()
            for offset in range(0, len(audio), 2560):
                models.transcribe(stream, audio[offset:offset + 2560])
            text = models.transcribe(stream, b"", True)
            scores = models.score(text, candidates())
            print(json.dumps({"file": index, "transcript": text, "scores": scores, "ms": round((time.perf_counter() - started)*1000)}), flush=True)
