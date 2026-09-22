![Truss](icon.png)

# Truss Engine

Run streaming speech recognition and Laya locally for the Truss Home Assistant integration. It runs as a normal Docker service on Linux; the HA OS app is optional.

## Linux / Home Assistant Container

From the repository root, generate a token and put it in a `.env` file beside `compose.yaml`:

```sh
openssl rand -hex 32
```

```dotenv
TRUSS_API_TOKEN=paste-the-generated-secret-here
```

Then build and start the engine:

```sh
docker compose up -d --build
docker compose logs -f truss-engine
```

Wait for `Truss models are ready`. In the Truss integration, set the engine URL to `http://YOUR_LINUX_HOST_LAN_IP:10350` and use the same `TRUSS_API_TOKEN` value. Do not use `localhost`: from Home Assistant's container, it means the HA container rather than this engine.

`compose.yaml` keeps models in a named Docker volume and starts the engine again after a reboot.

For a native Windows installation, use `scripts/run_engine_windows.ps1` from the repository root; the main [README](../README.md#native-windows-engine) has the setup steps.

## Home Assistant OS app
