"""Entry point for the Supervisor app and standalone container."""
import json
import logging
import os
from pathlib import Path
import secrets
from aiohttp import web
from engine.server import create_app


def engine_token(options, token_file, environment_token=""):
    """Return an explicit token or create one once in persistent engine data."""
    configured = environment_token or options.get("api_token", "")
    if configured:
        return configured, False
    if token_file.exists():
        return token_file.read_text(encoding="utf-8").strip(), False
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    try:
        with token_file.open("x", encoding="utf-8") as handle:
            handle.write(token + "\n")
        try:
            token_file.chmod(0o600)
        except OSError:
            pass  # Windows does not implement POSIX file modes.
        return token, True
    except FileExistsError:
        return token_file.read_text(encoding="utf-8").strip(), False


def decision_options(options, environment):
    result = dict(options)
    for variable, key in (("TRUSS_DECISION_BACKEND", "decision_backend"),
                          ("TYPESAFE_API_KEY", "typesafe_api_key"),
                          ("TYPESAFE_MODEL", "jev_model")):
        if environment.get(variable):
            result[key] = environment[variable]
    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    default_data = Path("/data") if Path("/data").is_dir() else Path(__file__).resolve().parent / "data"
    options_file = Path(os.environ.get("TRUSS_OPTIONS", default_data / "options.json"))
    options = json.loads(options_file.read_text()) if options_file.exists() else {}
    options = decision_options(options, os.environ)
    token_file = Path(os.environ.get("TRUSS_TOKEN_FILE", options_file.parent / "truss_engine_token"))
    token, created = engine_token(options, token_file, os.environ.get("TRUSS_API_TOKEN", ""))
    options["api_token"] = token
    if created:
        logging.warning("Truss pairing token (copy it into Home Assistant now; it will not be shown again): %s", token)
    os.environ.setdefault("HF_HOME", str(default_data / "huggingface"))
    port = int(os.environ.get("TRUSS_PORT", "10350"))
    web.run_app(create_app(options), host="0.0.0.0", port=port, access_log=None)
