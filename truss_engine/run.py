"""Entry point for the Supervisor app and standalone container."""
import json
import logging
import os
from pathlib import Path
from aiohttp import web
from engine.server import create_app

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    options_file = Path(os.environ.get("TRUSS_OPTIONS", "/data/options.json"))
    options = json.loads(options_file.read_text()) if options_file.exists() else {}
    if os.environ.get("TRUSS_API_TOKEN"):
        options["api_token"] = os.environ["TRUSS_API_TOKEN"]
    os.environ.setdefault("HF_HOME", "/data/huggingface")
    port = int(os.environ.get("TRUSS_PORT", "10350"))
    web.run_app(create_app(options), host="0.0.0.0", port=port, access_log=None)
