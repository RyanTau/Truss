"""Run real local ASR + Laya on a PCM16 WAV. Never connects to HA or executes."""
import argparse
import asyncio
import json
from pathlib import Path
import sys
import time
import wave
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "truss_engine"))
from engine.models import LocalModels
from engine.streaming import LiveDecisions


async def run(wav_path, threads, model_path=""):
    models = LocalModels({"threads": threads, "bundled_stt": True, "device": "cpu", "laya_model_path": model_path})
    print("Loading real local models...", flush=True)
    await asyncio.to_thread(models.load)
    candidates = [
        {"id": "light.kitchen:on", "label": "Turn on the kitchen light", "entity_id": "light.kitchen", "area": "Kitchen", "aliases": []},
        {"id": "light.kitchen:off", "label": "Turn off the kitchen light", "entity_id": "light.kitchen", "area": "Kitchen", "aliases": []},
        {"id": "light.bedroom:on", "label": "Turn on the bedroom light", "entity_id": "light.bedroom", "area": "Bedroom", "aliases": []},
        {"id": "light.bedroom:off", "label": "Turn off the bedroom light", "entity_id": "light.bedroom", "area": "Bedroom", "aliases": []},
    ]
    for text in ("Turn on the kitchen light", "Turn off the bedroom light", "Do not turn on the kitchen light", "Turn on"):
        start = time.perf_counter()
        scores = await asyncio.to_thread(models.score, text, candidates)
        print(json.dumps({"text": text, "probabilities": scores, "ms": round((time.perf_counter() - start) * 1000)}), flush=True)
    with wave.open(str(wav_path), "rb") as wav:
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, 16000):
            raise ValueError("Provide a mono PCM16 WAV at 16000 Hz")
        audio = wav.readframes(wav.getnframes())
    audio_ended = False
    events = []
    start = time.perf_counter()
    asr_pool, model_pool = ThreadPoolExecutor(1), ThreadPoolExecutor(1)
    loop = asyncio.get_running_loop()

    async def score(text, choices):
        return await loop.run_in_executor(model_pool, models.score, text, choices)

    async def emit(event):
        event = {**event, "audio_ended": audio_ended, "elapsed_ms": round((time.perf_counter() - start) * 1000)}
        events.append(event)
        print(json.dumps(event), flush=True)

    decisions = LiveDecisions(score, emit, candidates)
    task = asyncio.create_task(decisions.run())
    stream = models.create_stream(candidates)
    try:
        for offset in range(0, len(audio), 2560):
            target = start + offset / 32000
            await asyncio.sleep(max(0, target - time.perf_counter()))
            text = await loop.run_in_executor(asr_pool, models.transcribe, stream, audio[offset:offset + 2560])
            await decisions.update(text)
        audio_ended = True
        await decisions.update(await loop.run_in_executor(asr_pool, models.transcribe, stream, b"", True))
        decisions.finish()
        await task
        print(json.dumps({"live_probability_events": sum(e["type"] == "probabilities" and not e["audio_ended"] for e in events), "final_transcript": decisions.text}), flush=True)
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        asr_pool.shutdown(wait=False)
        model_pool.shutdown(wait=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("wav", type=Path)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--laya-model-path", default="", help="Optional existing Laya checkpoint directory")
    args = parser.parse_args()
    asyncio.run(run(args.wav, args.threads, args.laya_model_path))
