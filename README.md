<img src="https://raw.githubusercontent.com/RyanTau/Truss/main/icon.png" alt="Truss: a thought bubble containing a sound wave" width="128" height="128">

# Truss Live Voice for Home Assistant

**Act while you speak.** Truss streams Assist microphone audio to a local engine, updates Laya's action probabilities on each changed partial transcript, and calls Home Assistant's MCP tools as soon as an action crosses your threshold. There is no separate web UI.

**Experimental development release:** transport tests and a real offline Laya/ASR smoke test pass, including live probabilities during audio. However, the real test also exposed missed commands and transcription errors: this is **not yet a reliable everyday voice controller**. A real HA installation, physical satellite, and container builds remain untested. See [measured results and limitations](docs/VALIDATION.md).

[![Add Truss to Home Assistant](https://my.home-assistant.io/badges/config_flow.svg)](https://my.home-assistant.io/redirect/config_flow/?domain=truss)
[![Set up Home Assistant MCP](https://my.home-assistant.io/badges/config_flow.svg)](https://my.home-assistant.io/redirect/config_flow/?domain=mcp_server)

The **first badge configures an already installed integration**; it does not download custom components. Install the files and restart HA first. The second badge adds HA's official MCP server.

<!-- INSTALL_BADGES_START -->
[![Download with HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=RyanTau&repository=Truss&category=integration)
[![Add Truss app repository](https://my.home-assistant.io/badges/supervisor_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FRyanTau%2FTruss)
<!-- INSTALL_BADGES_END -->

The Truss icon is included in the integration and companion app. Local integration branding requires **HA 2026.3+**; HA 2026.1/2026.2 and some HACS listing views may still show a placeholder. The minimum HA version remains **2026.1.0**. See [icon support and installation details](docs/BRANDING.md).

## What is included

| Part | Installed where | Responsibility |
| --- | --- | --- |
| `custom_components/truss` | HA Core through HACS or manual copy | Native configuration, MCP autodetection/validation, entity selection, streaming STT bridge, execution, Assist response |
| `truss_engine` | Linux Docker service beside HA, or optional HA OS app | Local streaming sherpa-onnx transcription and local Laya inference |

```text
Assist microphone → Truss Live STT → streamed PCM audio → Truss engine
                                                        ├─ local ASR or external streaming STT
                                                        └─ partial transcript → local Laya
                         HA integration ← probabilities ←───────────┘
                              ↓ threshold met (before speech ends)
                         HA MCP server → device action
```

The engine never receives your HA access token. The integration executes fixed, discovered MCP calls; model output only selects among allowed actions.

## Requirements

- Home Assistant **2026.1 or later**, with an Assist-compatible microphone (Companion app, Voice device, ESPHome satellite, etc.). The minimum is set to 2026.1.0. Truss uses MCP Streamable HTTP and Assist voice APIs; installation on the minimum version still needs runtime validation.
- HA's official **Model Context Protocol Server**, with **Assist API** selected and **Control Home Assistant** enabled.
- A long-lived access token for the **same HA instance**. MCP autodetection suggests the existing HA URL; it does not generate credentials or scan the network.
- A computer running the Truss engine, or HA OS with the companion app installed. Python 3.12 is used in the container. Packaged inference uses CPU.
- Space for PyTorch, Laya, the transcription model, and cache. Pinned model files total about 0.92 GB; reserve several GB for the full installation and benchmark RAM/CPU on your machine. Initial startup downloads model files; subsequent inference is local.

## Installation: Home Assistant on Linux

This is the normal setup for Home Assistant installed as a Linux app or container. HACS installs only `custom_components/truss`; run the Truss engine separately on the same Linux host or another trusted Linux machine.

1. Install Truss through HACS as an **Integration**, then restart Home Assistant.
2. Clone this repository on the Linux machine that will run the engine. From its repository root, start the engine:

   ```sh
   docker compose up -d --build
   docker compose logs -f truss-engine
   ```

   On its first start, Truss logs a generated **pairing token** once. Copy it before continuing. Wait for `Truss models are ready`; the first start downloads the models and can take several minutes.
3. In Home Assistant, add **Truss Live Voice**. Enter `http://YOUR_LINUX_HOST_LAN_IP:10350` as its engine URL and paste the pairing token as the engine token. From Home Assistant Container, `localhost` is the HA container, so it cannot reach the engine that way.
5. Continue with [Configure Truss](#configure-truss).

`compose.yaml` stores models and the generated pairing token in a Docker volume and uses `restart: unless-stopped`, so the engine restarts with Docker. Keep port 10350 on your trusted LAN. The engine does not need, receive, or store your Home Assistant long-lived access token. Set `TRUSS_API_TOKEN` in a `.env` file only if you prefer to manage the token yourself.

## Optional: Home Assistant OS app

For an unpublished local test, copy the `truss_engine` folder to `/addons/truss_engine` on HA OS using Samba or SSH, then refresh the app store and find **Truss Local Engine** under local apps. Continue at step 3 below, using the manual integration install in step 4. This follows HA's [local app development workflow](https://developers.home-assistant.io/docs/apps/testing/#remote-development). No GitHub publication is needed for this path.

For repository installation:

1. Repository: [RyanTau/Truss](https://github.com/RyanTau/Truss). These project files must be published at its root before repository installation will work.
2. In **Settings → Apps → App store → Repositories**, add that URL. On versions with older wording, this is **Add-ons → Add-on store**.
3. Install **Truss Local Engine**. Leave `api_token` blank to have Truss generate a pairing token on first start, or set one yourself; leave `bundled_stt: true`. Copy the generated token from the first-start log and wait for **Truss models are ready**. The first local image build downloads large dependencies.
4. Install the integration using either:
   - **HACS → Custom repositories**: add the repository URL as an **Integration**, then download Truss; or
   - Copy `custom_components/truss` into `/config/custom_components/truss`. Alternatively, run `python scripts/package_release.py` and extract `dist/truss-manual-install.zip` into `/config` (it contains the `custom_components/truss` path).
5. Restart Home Assistant. Use the **Add Truss** badge above, or **Settings → Devices & services → Add integration → Truss Live Voice**.

The companion app runs models in its own environment; the integration never installs PyTorch into HA Core.

## Native Windows engine

You can run Truss directly on a Windows PC; Docker is optional. The PC must remain on while you use voice control. Install [Python 3.12 (64-bit)](https://www.python.org/downloads/release/python-3120/) and ensure the `py` launcher is available. Clone or download this repository, then run PowerShell from its root:

```powershell
.\scripts\run_engine_windows.ps1 -Install
```

The first start installs the Python dependencies, generates and displays a pairing token once, then downloads the models. Copy that token. On later starts, omit `-Install`:

```powershell
.\scripts\run_engine_windows.ps1
```

Keep the PowerShell window running. In the Truss integration, use `http://YOUR_WINDOWS_PC_LAN_IP:10350` and the generated pairing token. Do not use `localhost` unless Home Assistant itself is running directly on that same Windows PC. Windows Defender Firewall may ask to permit Python on private networks; allow that so Home Assistant can reach the engine. Pass `-ApiToken` only if you prefer to manage the token yourself.

## Configure Truss

1. **MCP**: the flow detects a configured MCP integration and suggests your HA URL plus `/api/mcp`. Correct it if necessary. Enter your profile's long-lived access token. Setup initializes MCP and checks that compatible Assist tools are actually present. Use this HA instance, not another server: entity discovery is local to HA.
2. **Engine**: enter `http://YOUR_HA_LAN_IP:10350` (or your separate engine host), and the engine's API token. `localhost` inside HA Container is not your separate Docker container.
3. **Transcription**: choose **Run locally with Truss** for the bundled English streaming Zipformer model. Or choose **External sherpa-onnx streaming server** (for example `ws://YOUR_STT_HOST:6006`) or **External Truss-protocol WebSocket**, and enter its URL/token. See the protocol requirements below.
4. **Device selection**: use **All supported entities exposed to Assist** (the default for new installs), **Assist entities in selected rooms**, or **Choose individual entities**. Automatic modes refresh each utterance as Assist exposure and room assignments change. Room mode uses the entity's room or its device's room if none is assigned. Manage exposure under **Settings → Voice assistants → Expose**. The scope must contain 1–24 entities; choose fewer rooms or use manual selection if there are more. Truss rejects an oversized scope rather than silently dropping devices. Existing installations keep their manual selection until you change it. Start with 2–4 devices for lower latency.
5. **Threshold**: defaults to `0.95`, with a `0.05` lead over the next candidate. Set the margin to `0` if you want threshold-only execution (exact ties still wait). There is no forced wait for silence or consecutive-update delay. Scores for an unchanged spoken prefix remain eligible when more words are appended; rewritten earlier words invalidate them. An action can therefore happen before a later spoken correction.
6. Under **Settings → Voice assistants**, create/edit an assistant:
   - Language: English.
   - Speech-to-text: **Truss Live**.
   - Conversation agent: **Truss Response**.
   - **Disable “Prefer handling commands locally”** if shown. Truss already handled the command during STT.
   - Text-to-speech: your existing provider, e.g. Piper.
7. Assign that assistant to your voice device and speak a supported request.

Both Truss entities must be selected together. STT returns an opaque per-session receipt to the conversation agent, which reports the result without repeating the action. HA's final STT trace therefore shows a receipt rather than the spoken text; live transcript events are available below. Typed chat through Truss Response is not implemented.

## Supported commands in 0.1.4

- Turn **lights, switches, fans, and input booleans** on/off.
- Activate **scenes and scripts**.
- Explicit entity names, aliases, and room descriptions contribute to Laya's interpretation.
- **One action per utterance**, including at most one attempt if MCP times out. No automatic retry of a possibly executed action.

Brightness, temperature, covers, timers, multi-action commands, and implicit “this room” resolution are not implemented. The STT entity interface does not supply the satellite's device ID to this bridge; name the device explicitly. Add broader parameter extraction and intent mappings as separate work. MCP tool names and schemas are discovered, not assumed to accept arbitrary service calls.

Laya evaluates up to four concrete actions plus a `wait` choice per forward pass. Returned values are the model's action probabilities; the omitted `wait` choice retains some probability mass. With multiple groups, scores are local to each group and do not form a single whole-home probability distribution. The model is not trained here on partial speech: empirical calibration and latency evaluation remain necessary. A configured threshold is an execution rule, not a reliability guarantee. Long entity lists mean more model work; no “33 ms whole-home control” claim is made.

## External transcription, Whisper, and Ollama

External STT must return **partial transcripts while audio is still arriving**. Supported protocols are the native sherpa-onnx streaming server and [the Truss streaming protocol](docs/PROTOCOL.md). Laya still runs locally in the Truss engine. The engine connects to the STT URL, so that address must be reachable from the app/container.

- The bundled **sherpa-onnx streaming Zipformer** is the immediately supported live transcription option. It downloads quantized model files, reuses a loaded recognizer, and keeps a separate stream per utterance.
- For an existing server, select **External sherpa-onnx streaming server**. This adapter implements the official [sherpa-onnx streaming server protocol](https://github.com/k2-fsa/sherpa-onnx/blob/master/python-api-examples/streaming_server.py), converting audio to float32 and joining transcript segments. Configure the server for 16 kHz English recognition. A Bearer token can authenticate a reverse proxy; the upstream example server itself does not enforce tokens.
- A Whisper streaming service can be connected **through an adapter implementing this protocol**. A standard `/v1/audio/transcriptions` file-upload endpoint or the ordinary HA Wyoming Whisper provider is not a drop-in live-partial endpoint. No Whisper adapter is included in this release.
- Stock **Ollama chat/generate streaming is text output streaming**, not this audio-to-partial-transcript protocol. Do not paste an Ollama URL into the STT field. An audio model hosted elsewhere needs a compatible streaming server/adapter.
- A generic external WebSocket passing the URL check is not proof of protocol compatibility; the first session validates actual messages. Only the protocols listed here are supported.

## Manual engine setup

`compose.yaml` above is the supported Linux path. To run the engine manually from this repository root:

```sh
docker build -t truss-engine ./truss_engine
```

Set `TRUSS_API_TOKEN` in your shell if you want to choose the token yourself. Otherwise the engine creates and prints a persistent pairing token on first start. Then:

```sh
docker run --name truss-engine --restart unless-stopped \
  -p 10350:10350 -e TRUSS_API_TOKEN \
  -v truss-models:/data truss-engine
```

PowerShell uses backticks rather than backslashes for multiline commands; the Docker command can also be entered on one line. Keep this port on a trusted network, or terminate HTTPS/WSS at a reverse proxy. Tokens authenticate both health and streaming endpoints. Audio is not saved by the engine.

For local development with Python 3.12, create a virtual environment, install CPU PyTorch and `truss_engine/requirements.txt`, set `TRUSS_API_TOKEN` and a writable `HF_HOME`, then run `python truss_engine/run.py`. Custom options can be loaded from a JSON file via `TRUSS_OPTIONS`; see `truss_engine/config.yaml` for keys.

## Observe live decisions without a custom UI

In **Developer tools → Events**, listen to:

- `truss_probabilities`: session ID, transcript revision, live text, per-action probabilities, inference time, and whether an action has already fired.
- `truss_action`: selected entity/action and `accepted` or `failed_or_unconfirmed`.
- `truss_session`: completed session summary with audio duration (`audio_ms`), elapsed time, partial transcript/score counts, transcript character count, and result. Contains no transcript or token. `no_audio` means no audio bytes reached Truss; `no_transcript` means audio arrived but no final speech text was recognized; `below_threshold` means scores were received but no action qualified. Empty audio and missing transcripts also produce a warning in Home Assistant's log. If Assist finishes immediately, inspect this event before adjusting the threshold and check any changes made to Home Assistant's voice activity detection.

`accepted` means the MCP tool reported success. This version does not independently verify physical device state after the call. Events include transcripts and entity IDs; treat HA event access accordingly. Diagnostics omit tokens, transcripts, URLs, and entity names.

## Development and checks

```sh
python -m unittest discover -s tests -v
python scripts/check_package.py
```

For a real-model check without executing any HA actions, run `python scripts/smoke_models.py path/to/mono-16khz-pcm16.wav`. It prints action scores, incremental transcripts, inference timing, and whether probability events arrived before the recording ended. The first run downloads the pinned model files.

The tests use simulated models/servers to verify streaming before end-of-speech, rejection of rewritten transcripts, acceptance of unchanged prefixes, deduplication, authentication, error handling, and MCP transport. They do not establish real-model accuracy or physical-device compatibility.

The repository identity is configured for **RyanTau/Truss**. To regenerate its publication metadata and install badges:

```sh
python scripts/set_repository.py https://github.com/RyanTau/Truss
```

This replaces metadata URLs, sets the GitHub code owner, and adds working HACS/app repository image links. Push the **contents of this directory as the repository root**, not the parent workspace, so HACS and Supervisor can find their manifests. The badges cannot download an unpublished repository or bypass HACS installation/restart.

## Architecture and references

- [Home Assistant STT entities](https://developers.home-assistant.io/docs/core/entity/stt/)
- [Home Assistant MCP Server](https://www.home-assistant.io/integrations/mcp_server/)
- [Home Assistant Assist pipelines](https://developers.home-assistant.io/docs/voice/pipelines/)
- [Laya](https://github.com/NandhaKishorM/laya)
- [Streaming sherpa-onnx](https://k2-fsa.github.io/sherpa/onnx/python/real-time-speech-recongition-from-a-microphone.html)
- [External STT / engine protocol](docs/PROTOCOL.md)
- [Release verification checklist](docs/RELEASE.md)

No core patches, browser automation, cloud LLM calls, or standalone dashboard are involved.
