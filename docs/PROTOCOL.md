# Truss streaming protocol v1

Since 0.1.7, text clients may send a normal start message with `stt: {"mode": "text"}` and a top-level `text` string of 1–1000 characters. Keep `sample_rate: 16000` for envelope compatibility. Do not send audio or an end message. The engine bypasses transcription and emits partial, probabilities, and done using the same decision path. Name resolution now allows close misspellings and unique shortened names; `resolved_action` scores remain conditional on that resolution.

There are two different WebSocket roles. Neither is an OpenAI-compatible audio upload API, Ollama endpoint, nor a Wyoming TCP endpoint.

## HA integration → Truss engine

Authenticate `GET /health` and `GET /v1/stream` with `Authorization: Bearer <engine token>`. `/health` returns `protocol: truss-v1`, `ready`, `bundled_stt`, and startup status. Do not open an audio stream until ready.

First WebSocket message:

```json
{"type":"start","session_id":"unique-id","language":"en","sample_rate":16000,"candidates":[{"id":"light.kitchen:on","entity_id":"light.kitchen","name":"Kitchen light","label":"Turn on Kitchen light","area":"Kitchen","aliases":[]}],"stt":{"mode":"bundled"}}
```

For external transcription, `stt` is `{"mode":"external","url":"ws://host:port/path","token":"optional secret"}`. The HA MCP token is never included.

Send binary frames containing **raw signed 16-bit little-endian mono PCM, 16 kHz**, not WAV headers. Send `{"type":"end"}` after the audio. Sessions are limited to 60 seconds of audio, 75 seconds wall time, 48 concrete candidates, and two concurrent clients.

In 0.1.6, candidate IDs follow `entity_id:on` or `entity_id:off` (scene/script activation uses `on`). Optional `name` supplies the friendly name; older clients fall back to the label with its operation prefix removed. Names and aliases provide per-session bundled-ASR hints. The engine resolves one explicit device and operation, then Laya confirms that action against wait. In `score_scope: resolved_action`, only the resolved action can have a nonzero probability; other zeros mean ineligible. If resolution fails, all scores are zero and no Laya forward pass is needed. The eligible action's score is the model's conditional execute probability, not a global device-choice distribution. It is not renormalized or boosted. The omitted wait choice retains the remaining mass. Original transcript text is preserved in events; inference casing is standardized to uppercase. `/health` includes `engine_version` and `score_scope`.

Server messages:

```json
{"type":"partial","revision":1,"text":"turn on the kitchen light"}
{"type":"probabilities","revision":1,"current_revision":1,"text":"turn on the kitchen light","probabilities":{"light.kitchen:on":0.97},"score_scope":"resolved_action","inference_ms":123.4}
{"type":"done","revision":1,"text":"turn on the kitchen light"}
```

Partial texts replace the complete hypothesis; they are not appended deltas. If an earlier word changes while inference runs, its result is discarded. If the new hypothesis only appends words at a word boundary, the scored prefix remains eligible: this permits action during continuous speech even when inference takes longer than an ASR update interval. `revision` and `text` identify the actual scored prefix; `current_revision` identifies the latest hypothesis at emission. The integration independently checks the prefix against its latest text. A later spoken correction cannot undo an action already issued. Pending inference coalesces to the newest hypothesis, with no unbounded queue. Every actionable event must contain a complete, finite [0,1] score vector. The HA integration owns thresholds and execution. `inference_ms` includes queue wait plus batched model work, not microphone-to-device latency.

`{"type":"error","message":"..."}` aborts the session. Disconnects/timeouts never trigger fallback actions or execution retries.

## Truss engine → external streaming STT endpoint

Provide a WebSocket service accepting an optional Bearer token and this initial text message:

```json
{"type":"start","sample_rate":16000,"format":"pcm_s16le","channels":1,"language":"en"}
```

The engine forwards binary PCM frames as received. It sends `{"type":"end"}` when Assist ends the utterance.

The provider must emit full-utterance hypotheses **before** receiving end:

```json
{"type":"partial","text":"turn on"}
{"type":"partial","text":"turn on the kitchen light"}
```

After the end message, send exactly one final full transcript, then optionally close:

```json
{"type":"final","text":"turn on the kitchen light"}
```

The final transcript must arrive within 15 seconds of audio ending. Individual transcript strings are capped at 1000 characters. Do not finalize at internal pauses while Assist continues sending audio; accumulate segment results into a complete hypothesis. Send `{"type":"error","message":"..."}` on failure.

To adapt a streaming Whisper service, forward PCM into its actual streaming API and translate its replacement/delta/segment results into these full hypotheses. The transport alone does not make a batch recognizer live. A native sherpa-onnx adapter is included; no Whisper-specific adapter is bundled.

## External sherpa-onnx mode

Set `stt.mode` to `sherpa`, with a `ws://` or `wss://` URL and optional Bearer token. This targets the official [Python streaming server](https://github.com/k2-fsa/sherpa-onnx/blob/master/python-api-examples/streaming_server.py) protocol, configured for 16 kHz recognition. It sends float32 little-endian audio normalized to [-1,1), no initial JSON, and the text `Done` at audio end. Incoming `{"segment":0,"text":"turn on"}` hypotheses replace the current segment; segments are joined into the full utterance. Normal closure after the final transcript completes the session. The C++ server's `Done!` terminator is also accepted. Early disconnects and incomplete PCM samples fail the session.

The integration-to-engine audio format remains PCM16 in every mode. The engine performs conversion; satellites require no changes. A configured STT token is sent only to the selected endpoint.
