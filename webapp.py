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
import ipaddress
import socket
from pathlib import Path
from urllib.parse import urlparse

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


def _origin_netloc(value: str) -> str:
    """Return the host:port portion of an Origin or Referer header."""
    return urlparse(value).netloc


def _is_loopback_host(host: str) -> bool:
    """True if the bind host stays on the local machine."""
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _is_safe_destination(url: str) -> bool:
    """True if the URL is http/https and every resolved address is public.

    Guards the upload route against reaching loopback or private-network
    services (SSRF). Checking all resolved records rejects a hostname that
    maps even partly into a private range.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False
    host = parsed.hostname
    if not host:
        return False
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port)
    except socket.gaierror:
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if (ip.is_loopback or ip.is_private or ip.is_link_local
                or ip.is_multicast or ip.is_reserved or ip.is_unspecified):
            return False
    return True


@app.before_request
def _block_cross_origin():
    """Reject state-changing requests whose Origin/Referer is not our own.

    This stops a web page the user happens to visit from driving the server
    through their browser, which matters once it binds a routable interface.
    """
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        origin = request.headers.get("Origin")
        referer = request.headers.get("Referer")
        if origin and _origin_netloc(origin) != request.host:
            return _error("Cross-origin request blocked.", 403)
        if not origin and referer and _origin_netloc(referer) != request.host:
            return _error("Cross-origin request blocked.", 403)
    return None


# --------------------------------------------------------------------------- #
# Static / page
# --------------------------------------------------------------------------- #
@app.get("/")
def index():
    resp = send_from_directory(BASE_DIR / "web", "index.html")
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.get("/static/<path:filename>")
def static_files(filename: str):
    resp = send_from_directory(BASE_DIR / "web", filename)
    resp.headers["Cache-Control"] = "no-cache"
    return resp


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
    if not _is_safe_destination(url):
        return _error("That upload target is not allowed.")

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
        body = zp.zenpload(url=url, filename=filename, content_type=content_type,
                           data=data, allow_redirects=False)
        upload_obj = body["upload"]
        file_url = upload_obj["attachments"][0]["mapped_content_url"]
        expires_raw = upload_obj.get("expires_at", "")
    except zp.ZenploaderError as exc:
        app.logger.warning("upstream upload failed: %s", exc)
        return _error("The upload target rejected the request.", 502)
    except (KeyError, IndexError):
        return _error("Upload succeeded but the response had an unexpected shape.", 502)

    if urlparse(file_url).scheme not in ("http", "https"):
        app.logger.warning("upstream returned a non-web URL: %r", file_url)
        return _error("The upload target returned an unexpected URL.", 502)

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
    if not _is_loopback_host(args.host):
        print(
            f"WARNING: binding to {args.host} exposes this server to your "
            "network. Anyone who can reach it can upload through your "
            "configured sites, so only do this on a trusted network."
        )
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
