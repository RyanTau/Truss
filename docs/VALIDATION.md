# Development validation

## What was actually run

- 29 automated tests using real HTTP/WebSocket transports with simulated Home Assistant and model responses. These cover execution before audio end, exactly-once attempts, prefix continuation versus rewritten speech, exposure checks, MCP JSON/SSE, external STT protocols, authentication, and disconnects.
- Actual pinned English Laya and quantized streaming Zipformer models, running offline on CPU in a Windows Python 3.12 environment, with four threads. Installed versions: Laya 0.3.4, PyTorch 2.14.0+cpu, sherpa-onnx 1.13.8, transformers 5.17.0. Downloads were verified against upstream file hashes.
- A Windows speech-synthesized recording of “Turn on the kitchen light please,” streamed in real time as mono PCM16 at 16 kHz. No Home Assistant connection or real device action occurred in this model test.
- Manual integration ZIP structure and Python/JSON/translation checks.

## Real-model result

The [recorded output](validation/smoke-cpu.jsonl) is a smoke test, not an accuracy benchmark. Four candidate actions were available: kitchen and bedroom light on/off.

| Input / measurement | Observed result |
| --- | --- |
| Exact text: turn on the kitchen light | Correct action probability 0.9514; meets default 0.95 threshold |
| Exact text: turn off the bedroom light | Correct action ranks first at 0.5944; **misses the default threshold** |
| Negated kitchen command | Highest action probability 0.604; no action at default threshold, but lowering it could cause an unwanted action |
| Incomplete “Turn on” | Highest action probability 0.5127; no action at default threshold |
| Speech recording | Transcribed as “TURN ON THE KITCHEN LIKE PLEASE” |
| During the recording | Three actual model probability updates before audio ended |
| Live inference passes | Approximately 445–550 ms on this test machine; excludes microphone transport and MCP/device latency |
| Highest live kitchen-on score | 0.8748; **does not execute at default threshold** |
| Final kitchen-on score | 0.9226; still below default threshold |

The initial binary-per-action implementation was slower and confused opposite operations. Small multiple-choice groups improved the tested cases and latency, but **the current pretrained model is not sufficiently validated or reliable for general home control**. Threshold tuning alone does not fix incorrect rankings. A labelled corpus of household commands and partial transcripts, model adaptation, and hardware-specific latency work remain necessary.

You can inspect the threshold decision without loading models or contacting HA:

```sh
python scripts/replay_trace.py docs/validation/smoke-cpu.jsonl
python scripts/replay_trace.py docs/validation/smoke-cpu.jsonl --threshold 0.85
```

The default 0.95 produces no request for this recording. At 0.85, the recorded scores would request kitchen-on at 2326 ms, while audio was still arriving. This is a replay of one synthetic recording, not a recommendation to lower the threshold for general use.

Scored prefixes remain usable when ASR only appends words; otherwise continuously arriving words can starve decisions. Earlier-word rewrites invalidate a pending score. This deliberately allows commitment before the user finishes their sentence.

The pinned model files total approximately 0.92 GB. The Windows test environment additionally used approximately 0.72 GB for Python packages and 0.13 GB for Python itself, excluding package caches and temporary downloads. These are not Linux container size or minimum RAM estimates.

## Not yet verified

Actual HA config/options flows and MCP server, physical voice satellites and devices, Docker/Supervisor builds, ARM performance, other microphones/accents/noise, and deployment against an actual external sherpa server. External-protocol adapters were tested with protocol simulators. Follow [the release checklist](RELEASE.md) before publishing compatibility claims.

## Home Assistant minimum version

Version 0.1.2 sets the declared minimum to 2026.1.0 at the maintainer's request. The previous 0.1.1 compatibility review examined 2025.11.0: source review confirmed the [MCP Streamable HTTP endpoint](https://github.com/home-assistant/core/blob/2025.11.0/homeassistant/components/mcp_server/http.py), STT stream entity interface, conversation processing/control feature, exposure lookup, and options-flow config entry API at that tag. HA 2025.10.0's MCP implementation uses the older separate SSE transport; Truss does not implement that transport. The add-on uses the legacy-compatible `io.hass.type=addon` Docker label. This source review does not replace installing and exercising both the minimum and current HA releases.
