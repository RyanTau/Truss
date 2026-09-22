"""Fill publication metadata and install badges with the real GitHub identity."""
import argparse
import json
from pathlib import Path
import re
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]


def configure(url):
    match = re.fullmatch(r"https://github\.com/([A-Za-z0-9-]+)/([A-Za-z0-9_.-]+)/?", url)
    if not match:
        raise ValueError("Use https://github.com/OWNER/REPOSITORY")
    owner, repo = match.groups()
    url = f"https://github.com/{owner}/{repo}"
    path = ROOT / "custom_components/truss/manifest.json"
    manifest = json.loads(path.read_text())
    manifest.update(documentation=url, issue_tracker=url + "/issues", codeowners=["@" + owner])
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (ROOT / "repository.yaml").write_text(f"name: Truss Home Assistant Apps\nurl: {url}\nmaintainer: {owner}\n", encoding="utf-8")
    app_config = ROOT / "truss_engine/config.yaml"
    app_text = app_config.read_text(encoding="utf-8")
    app_url = f"url: {url}"
    if re.search(r"^url:.*$", app_text, flags=re.M):
        app_text = re.sub(r"^url:.*$", app_url, app_text, flags=re.M)
    else:
        app_text = app_text.rstrip() + "\n" + app_url + "\n"
    app_config.write_text(app_text, encoding="utf-8")
    readme = ROOT / "README.md"
    badges = (
        f"[![Download with HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner={owner}&repository={repo}&category=integration)\n"
        f"[![Add Truss app repository](https://my.home-assistant.io/badges/supervisor_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_addon_repository/?repository_url={quote(url, safe='')})"
    )
    text = re.sub(r"(?<=<!-- INSTALL_BADGES_START -->).*?(?=<!-- INSTALL_BADGES_END -->)", "\n" + badges + "\n", readme.read_text(encoding="utf-8"), flags=re.S)
    readme.write_text(text, encoding="utf-8")
    print("Publication metadata configured for", url)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    configure(parser.parse_args().url)
