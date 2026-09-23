![Truss](icon.png)

# Truss Engine

Run streaming speech recognition with local LAYA or hosted Jev decisions for the Truss Home Assistant integration. It runs as a normal Docker service on Linux; the HA OS app is optional.

For Jev setup without local LAYA, see [Jev configuration](../docs/JEV.md). Jev sends partial transcripts and selected device descriptions to TypeSafe; an API key and internet access are required.

## Linux / Home Assistant Container

From the repository root, build and start the engine:

```sh
docker compose up -d --build
docker compose logs -f truss-engine
```

On first start, Truss prints a generated pairing token once. Copy it, then wait for `Truss models are ready`. In the Truss integration, set the engine URL to `http://YOUR_LINUX_HOST_LAN_IP:10350` and use that token. Do not use `localhost`: from Home Assistant's container, it means the HA container rather than this engine.

`compose.yaml` keeps models and the generated token in a named Docker volume and starts the engine again after a reboot. You can set `TRUSS_API_TOKEN` in `.env` if you prefer to manage your own token.

For a native Windows installation, use `scripts/run_engine_windows.ps1` from the repository root; the main [README](../README.md#native-windows-engine) has the setup steps.

## Home Assistant OS app
