# Use Jev instead of LAYA

Truss can use TypeSafe's hosted **Jev** model for action probabilities. The browser-use/jev-ultrafast project is a browser agent powered by this API; Truss calls the underlying decision API directly, without installing a browser agent or a text-generation model.

Sources: [TypeSafe API](https://docs.typesafe.ai/api), [models](https://docs.typesafe.ai/models), [Jev browser example](https://github.com/browser-use/jev-ultrafast/blob/main/jev_ultrafast/model.py).

## What changes

- Select `decision_backend: jev` on the **engine**, then restart it. The HA integration continues connecting to the same engine URL and pairing token.
- Jev mode does not import, load, or download LAYA or PyTorch. The lightweight Docker/Windows installation below also avoids installing them. Existing cached models are left untouched.
- Transcription is separate: bundled sherpa-onnx, an external streaming transcription server, and completed text inputs continue to work. Jev does not transcribe audio. The Truss engine is still required as the bridge.
- Each scored partial sends its text and selected device descriptions (names, aliases, rooms, action labels) to TypeSafe over HTTPS. Audio, the HA access token, MCP tool arguments, and the Truss pairing token are not sent to TypeSafe.
- This requires internet access and a TypeSafe API key. API billing and limits apply; a single utterance can produce multiple requests. Intermediate transcripts are coalesced when inference is busy. No automatic API retries or fallback to LAYA are performed.
- Existing execution thresholds, streaming events, and execution checks remain. The threshold is an action probability, not the separate TypeSafe `confidence` field. Retest thresholds against Jev rather than assuming LAYA scores transfer.

## Native Windows / PowerShell

Stop the current engine, update the repository, and run:

```powershell
$env:TYPESAFE_API_KEY = "YOUR_TYPESAFE_API_KEY"
$env:TYPESAFE_MODEL = "jev-latest"
.\scripts\run_engine_windows.ps1 -DecisionBackend jev -Install
```

Subsequent starts can omit `-Install`. Keep `TYPESAFE_API_KEY` configured in the launching environment. To return to local LAYA, run with `-DecisionBackend laya -Install`.

For your own Cygwin or Linux launcher, install `truss_engine/requirements-base.txt` into that launcher's Python environment and set:

```bash
export TRUSS_DECISION_BACKEND=jev
export TYPESAFE_API_KEY='YOUR_TYPESAFE_API_KEY'
export TYPESAFE_MODEL=jev-latest
```

Then use your existing launcher so its token and cache paths remain unchanged. Environment variables override matching options-file settings.

## Docker Compose

In the repository's ignored `.env` file, add:

```dotenv
TRUSS_DECISION_BACKEND=jev
TYPESAFE_API_KEY=YOUR_TYPESAFE_API_KEY
TYPESAFE_MODEL=jev-latest
```

Rebuild and restart:

```bash
docker compose up -d --build
```

The Jev build installs only the base dependencies, without LAYA/PyTorch. Switching back to `laya` requires rebuilding. The existing persistent pairing-token/model volume is retained.

## Home Assistant OS app

In the Truss engine app's Configuration, choose:

```yaml
decision_backend: jev
typesafe_api_key: YOUR_TYPESAFE_API_KEY
jev_model: jev-latest
```

Keep other settings, save, and restart the app. The standard Supervisor image contains LAYA dependencies for compatibility, but Jev mode never loads or downloads its model. Use the Jev Compose build if you also want to avoid installing those dependencies.

## Configuration files

The same three keys work in the engine's `options.json`, or a file selected with `TRUSS_OPTIONS`. `bundled_stt: false` skips speech-model downloads when using external transcription or text-only input. Do not select Truss bundled transcription in HA when it is disabled on the engine.

Keep the existing `api_token` or persistent token-file configuration. `typesafe_api_key` authenticates the engine to TypeSafe; it is different from the engine pairing token entered into HA.

## Verify and troubleshoot

Authenticated `/health` reports `decision_backend: jev`, `decision_model`, and readiness. Ready means the local engine has started; it does **not** certify that the TypeSafe account/key has been accepted. The first command validates that through a real evaluation request.

With integration 0.1.10, `truss_probabilities` includes `decision_backend: jev`. The API uses the documented `https://api.typesafe.ai/v1/systemone` endpoint and defaults to `jev-latest`; set `jev_model`/`TYPESAFE_MODEL` to a supported versioned ID if you need to pin behavior.

Missing keys prevent Jev startup. HTTP errors, timeouts, redirects, and malformed/missing probability vectors fail the session without executing from that response. An action already committed earlier in the session cannot be undone by a later provider failure. Engine logs report HTTP status without the API key or provider response body. A 401 indicates an invalid key; 429 indicates rate limiting.

Validation is against an offline API-contract test server, including text with local model imports forbidden, live probabilities before audio end, malformed vectors, and provider errors. A fresh Windows environment installed only `requirements-base.txt`, confirmed LAYA and PyTorch were absent, and successfully transcribed a synthetic recording with the actual cached sherpa model. All eight Jev tests also passed in that environment. No production TypeSafe credentials were available during development; hosted accuracy, latency, and billing have not been measured. Windows launcher syntax is checked; a full launcher run and Docker image builds still need platform validation.
