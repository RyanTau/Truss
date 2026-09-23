# Local Nemotron live transcription

Engine **0.1.11** can use NVIDIA's English Nemotron Speech Streaming 0.6B through
the local NeMo-Speech.cpp runtime. Partial text feeds the existing LAYA or Jev
decision backend while audio is arriving. No Home Assistant integration update
is needed: keep **Truss Live** as speech-to-text, **Truss Response** as the agent,
and **bundled/local transcription** in Truss settings.

## Windows: one launcher

From the updated repository root in PowerShell:

```powershell
.\scripts\run_engine_windows.ps1 -SttBackend nemotron -Install
```

This installs the pinned NVIDIA runtime release **0.1.0**, checks its published
SHA-256, downloads its pinned English quantized model (about 668 MiB), starts
the runtime on **127.0.0.1:10351**, waits for readiness, and starts Truss on
**10350**. Keep using your existing Truss URL and pairing token in HA.
The launcher stops its runtime when Truss exits. Subsequent launches:

```powershell
.\scripts\run_engine_windows.ps1 -SttBackend nemotron
```

Jev users add `-DecisionBackend jev` and retain their `TYPESAFE_API_KEY` environment
variable. Nemotron does not require LAYA, PyTorch, or a paid transcription API.
The normal LAYA decision backend still installs its own Python dependencies.

The default Windows runtime backend is **Vulkan**, to avoid imposing recent CUDA
wheel requirements on older cards such as the GTX 1070. A working Vulkan graphics
driver is required; GTX 1070 performance has not been measured. To use CPU instead:

```powershell
.\scripts\run_engine_windows.ps1 -SttBackend nemotron -NemotronBackend cpu -Install
```

`-NemotronBackend cuda` is also available for compatible hardware/runtime builds.
There is no silent CPU or Zipformer fallback. Native runtime errors are recorded
in `data/nemotron.stderr.log` and `data/nemotron.stdout.log`. Downloads live under
`data/nemotron-models`; runtime binaries live under `.runtime`.
Windows release packages are x86-64 only in this installer.
Keep at least 1 GB free for installation (more for the Python/LAYA environment).

From Cygwin, call the PowerShell launcher from the repository root:

```sh
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/run_engine_windows.ps1 -SttBackend nemotron -Install
```

To return to the previous recognizer, launch with `-SttBackend sherpa`.

## Existing runtime, Linux, Docker, or HA OS

Install [NeMo-Speech.cpp](https://github.com/NVIDIA/NeMo-Speech.cpp) on the machine
performing recognition. Start an English streaming ASR server:

```sh
nemo-speech serve --asr-model nemotron-en --host 127.0.0.1 --port 10351 --no-ui --asr.streaming.rnnt_right_context 1 --asr.endpointing.enable=false
```

Set these engine environment variables, then restart Truss:

```text
TRUSS_STT_BACKEND=nemotron
TRUSS_NEMOTRON_URL=http://127.0.0.1:10351
```

On Windows, setting `TRUSS_NEMOTRON_URL` tells the launcher to use that existing
server rather than launch its own. The URL is a server origin, without a path.
`TRUSS_NEMOTRON_TOKEN` supplies an optional bearer token to a protected server.

For Docker, put the variables in `.env` and rebuild/recreate the engine. Use the
runtime's reachable address from the container, not container-local `127.0.0.1`.
Docker Desktop can use `host.docker.internal`; Linux can use the host LAN IP.
The runtime must listen on the corresponding interface for remote/container
access; configure its API key when exposing it outside loopback. The Truss image
does **not** install or launch the native runtime itself.

For the optional HA OS app, set `stt_backend: nemotron`, `nemotron_url` to the
reachable runtime origin, `nemotron_token` if configured, and `bundled_stt: true`.
Run the native runtime on a separate capable host. External STT selections and
typed Assist commands retain their existing behavior.

## Behavior and validation

- Right context `1` selects **160 ms audio chunks**. This is not end-to-end action
  latency. Change it to `6` on a manually started server for 560 ms chunks.
- Truss sends entity names and aliases as vocabulary hints (boost 3).
- The transport consumes native delta events immediately and replaces each
  tentative segment with its final transcript. It waits for the native commit
  acknowledgement after Assist ends audio, rather than ending on an early segment.
- Punctuation and endpointing are disabled in the managed runtime to keep interim
  text stable. The native protocol does not mark non-prefix partial rewrites;
  it should not be treated as a generic OpenAI Realtime endpoint.
- `/health` reports `stt_backend: nemotron` and checks native readiness. If the
  runtime was unavailable at Truss startup, start it and restart Truss.
- Audio remains local when the runtime is local. Initial installation downloads
  from GitHub and Hugging Face. Jev, if selected, still sends text to TypeSafe.
- Automated tests cover scores before audio ends, final replacement, odd packet
  boundaries, provider failures, and readiness. These do not establish accuracy
  on a real microphone, accents, background TV, or the GTX 1070.
- Validation here: all 63 tests and package checks passed; the real Windows CPU
  runtime launched and reported version 0.1.0. The model smoke test could not run
  because the development drive lacked space for the 700 MB model. Real ASR
  accuracy, throughput, and GPU initialization remain unverified.

Protocol implementation checked against NVIDIA source commit
`302ebc93f096d03395e5d86c643897b8bf0fd9a8` and its
[realtime API documentation](https://github.com/NVIDIA/NeMo-Speech.cpp/blob/302ebc93f096d03395e5d86c643897b8bf0fd9a8/docs/api.md).
