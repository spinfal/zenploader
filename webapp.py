#!/usr/bin/env python3
"""Zenploader web UI - a small Flask front end over the core upload logic.

Browsers can't POST directly to the Zendesk upload endpoints (CORS), so this
server does it for them. The core functions live in ``zenploader.py``; this
module only wires them to HTTP routes and serves the single-page UI.

Run it:

    pip install -r requirements.txt
    python webapp.py            # http://127.0.0.1:5000

Flags:

    --host HOST   interface to bind (default 127.0.0.1)
    --port PORT   port to bind (default 5000)
    --config PATH alternative config file
    --debug       Flask debug/reload
"""

from __future__ import annotations

import argparse
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

import zenploader as zp

BASE_DIR = Path(__file__).resolve().parent

app = Flask(__name__, static_folder=None)

# Resolved from CLI args in main(); falls back to the bundled config.
CONFIG_PATH = zp.DEFAULT_CONFIG


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _load() -> dict:
    return zp.load_config(CONFIG_PATH)


def _error(message: str, status: int = 400):
    return jsonify({"ok": False, "error": message}), status


# --------------------------------------------------------------------------- #
# Static / page
# --------------------------------------------------------------------------- #
@app.get("/")
def index():
    return send_from_directory(BASE_DIR / "web", "index.html")


@app.get("/static/<path:filename>")
def static_files(filename: str):
    return send_from_directory(BASE_DIR / "web", filename)


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #
@app.get("/api/sites")
def api_sites():
    try:
        cfg = _load()
    except zp.ZenploaderError as exc:
        return _error(str(exc), 500)
    return jsonify({"ok": True, "sites": zp.valid_sites(cfg)})


@app.post("/api/sites")
def api_add_site():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    url = (data.get("url") or "").strip()
    if not name:
        return _error("A site name is required.")
    if not (url.startswith(("http://", "https://")) and len(url) > 8):
        return _error("Enter a full URL starting with http:// or https://")

    try:
        cfg = _load()
    except zp.ZenploaderError as exc:
        return _error(str(exc), 500)

    if any(s.get("url") == url for s in cfg.get("sites", [])):
        return _error("A site with that URL already exists.")

    cfg.setdefault("sites", []).append({"name": name, "url": url})
    try:
        zp.save_config(CONFIG_PATH, cfg)
    except zp.ZenploaderError as exc:
        return _error(str(exc), 500)
    return jsonify({"ok": True, "sites": zp.valid_sites(cfg)})


@app.delete("/api/sites")
def api_remove_site():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    if not url:
        return _error("A site URL is required.")

    try:
        cfg = _load()
    except zp.ZenploaderError as exc:
        return _error(str(exc), 500)

    target = next((s for s in cfg.get("sites", []) if s.get("url") == url), None)
    if not target:
        return _error("No site with that URL.", 404)

    cfg["sites"].remove(target)
    try:
        zp.save_config(CONFIG_PATH, cfg)
    except zp.ZenploaderError as exc:
        return _error(str(exc), 500)
    return jsonify({"ok": True, "sites": zp.valid_sites(cfg)})


@app.post("/api/upload")
def api_upload():
    url = (request.form.get("url") or "").strip()
    if not (url.startswith(("http://", "https://")) and len(url) > 8):
        return _error("Pick a valid upload target first.")

    override_name = (request.form.get("filename") or "").strip()
    override_type = (request.form.get("content_type") or "").strip()

    upload = request.files.get("file")
    text = request.form.get("text")

    if upload is not None and upload.filename:
        data = upload.read()
        filename = override_name or upload.filename
        if override_type:
            content_type = override_type
        else:
            content_type = zp.guess_content_type(Path(filename))
            if content_type == "application/octet-stream" and upload.mimetype:
                content_type = upload.mimetype
    elif text is not None:
        data = text.encode("utf-8")
        filename = override_name or "untitled.txt"
        if not Path(filename).suffix:
            filename += ".txt"
        content_type = override_type or "text/plain"
    else:
        return _error("Nothing to upload - attach a file or send some text.")

    if not data:
        return _error("The payload is empty.")
    if len(filename) > zp.MAX_FILENAME_LEN:
        return _error(f"Filename too long (max {zp.MAX_FILENAME_LEN} characters).")

    try:
        body = zp.zenpload(url=url, filename=filename, content_type=content_type, data=data)
        upload_obj = body["upload"]
        file_url = upload_obj["attachments"][0]["mapped_content_url"]
        expires_raw = upload_obj.get("expires_at", "")
    except zp.ZenploaderError as exc:
        return _error(str(exc), 502)
    except (KeyError, IndexError):
        return _error("Upload succeeded but the response had an unexpected shape.", 502)

    return jsonify({
        "ok": True,
        "url": file_url,
        "expires_at": expires_raw,
        "expires_human": zp._format_expires(expires_raw) if expires_raw else "",
        "filename": filename,
        "content_type": content_type,
        "size": len(data),
    })


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def main() -> None:
    global CONFIG_PATH
    parser = argparse.ArgumentParser(prog="zenploader-web", description="Zenploader web UI.")
    parser.add_argument("--host", default="127.0.0.1", help="Interface to bind (default 127.0.0.1).")
    parser.add_argument("--port", type=int, default=5000, help="Port to bind (default 5000).")
    parser.add_argument("--config", default=str(zp.DEFAULT_CONFIG), help="Alternative config file.")
    parser.add_argument("--debug", action="store_true", help="Enable Flask debug/reload.")
    args = parser.parse_args()

    CONFIG_PATH = Path(args.config)
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
