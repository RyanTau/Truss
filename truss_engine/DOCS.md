# Truss Local Engine

This app runs English streaming sherpa-onnx transcription and local LAYA or hosted Jev inference. It contains no frontend. The separate Truss custom integration connects it to Assist and Home Assistant's MCP server.

1. Set `api_token` to a randomly generated secret of at least 24 characters (a password manager can generate it).
2. Keep `bundled_stt: true` to run transcription here. Set it to false only when you have a compatible external streaming STT endpoint.
3. Start the app. In default LAYA mode the first run downloads the pinned English Laya checkpoint and its tokenizer/config files. Bundled transcription downloads about 73 MB of quantized streaming Zipformer weights. Startup can take several minutes; watch for **Truss models are ready** in the app log.
4. Add the **Truss Live Voice** integration. Set the engine URL to `http://YOUR_HA_LAN_IP:10350` and enter the same API token. Keep the API on your trusted network; use TLS if crossing an untrusted network.

To use Jev, set `decision_backend: jev`, `typesafe_api_key`, and `jev_model: jev-latest` in Configuration, then restart. This skips the LAYA download/load. Partial transcripts and selected device descriptions are sent to TypeSafe; API billing and internet access apply. The engine pairing token remains separate. See [full Jev setup](https://github.com/RyanTau/Truss/blob/main/docs/JEV.md).

The models are cached in `/data/huggingface`. They survive an app restart. Allow several GB for dependencies and models. Runtime RAM and latency depend on hardware and the number of selected entities; no Raspberry Pi latency claim has been validated. Start with 2–4 entities. CPU inference is the supported packaged configuration.

`threads` controls CPU threads used by each model. `laya_model_path` optionally points at an existing compatible English Laya model inside the container; normally leave it blank. LAYA decisions run locally; selecting Jev uses the TypeSafe cloud API. Audio goes to an external service only if you explicitly configure external STT.

This app does not install the custom integration automatically. Install `custom_components/truss` through HACS or manually, then restart Home Assistant. It does not receive the MCP token; MCP execution remains inside the HA integration.

The `amd64` and `aarch64` build targets are declared; image builds and real hardware performance must be validated before a release.
