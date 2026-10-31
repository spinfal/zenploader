#!/usr/bin/env python3
"""Zenploader - abuse Zendesk help-desk upload APIs as a free file CDN.

Zendesk help desks expose an unauthenticated ``/api/v2/uploads.json`` endpoint
used to attach files to tickets. This tool posts a file (or plain text) to one
of those endpoints and returns the public, CDN-backed URL of the upload.

Run with no flags for a terminal UI (arrow-key site picker and file browser,
content type detected automatically), or drive it entirely from flags for
scripting. See ``--help`` for the full list.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import questionary
import requests
from rich.align import Align
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.rule import Rule
from rich.text import Text

CONSOLE = Console()
ERR = Console(stderr=True)

VERSION = "1.0.0"
DEFAULT_CONFIG = Path(__file__).resolve().parent / "config.json"
REQUEST_TIMEOUT = 30
MAX_FILENAME_LEN = 2048

# Content types that mimetypes misses or gets wrong on some platforms.
_EXTRA_TYPES = {
    ".md": "text/markdown",
    ".webp": "image/webp",
    ".apk": "application/vnd.android.package-archive",
    ".7z": "application/x-7z-compressed",
    ".rar": "application/vnd.rar",
    ".ts": "text/plain",
}
for _ext, _type in _EXTRA_TYPES.items():
    mimetypes.add_type(_type, _ext)

# Rendered once with pyfiglet (ANSI Shadow). Embedded so there is no runtime dep.
BANNER_LINES = [
    "███████╗███████╗███╗   ██╗██████╗ ██╗      ██████╗  █████╗ ██████╗ ███████╗██████╗ ",
    "╚══███╔╝██╔════╝████╗  ██║██╔══██╗██║     ██╔═══██╗██╔══██╗██╔══██╗██╔════╝██╔══██╗",
    "  ███╔╝ █████╗  ██╔██╗ ██║██████╔╝██║     ██║   ██║███████║██║  ██║█████╗  ██████╔╝",
    " ███╔╝  ██╔══╝  ██║╚██╗██║██╔═══╝ ██║     ██║   ██║██╔══██║██║  ██║██╔══╝  ██╔══██╗",
    "███████╗███████╗██║ ╚████║██║     ███████╗╚██████╔╝██║  ██║██████╔╝███████╗██║  ██║",
    "╚══════╝╚══════╝╚═╝  ╚═══╝╚═╝     ╚══════╝ ╚═════╝ ╚═╝  ╚═╝╚═════╝ ╚══════╝╚═╝  ╚═╝",
]
# Cyan to violet, one colour per banner row.
BANNER_GRADIENT = ["#22d3ee", "#38bdf8", "#60a5fa", "#818cf8", "#a78bfa", "#c084fc"]

QSTYLE = questionary.Style([
    ("qmark", "fg:#22d3ee bold"),
    ("question", "bold"),
    ("pointer", "fg:#22d3ee bold"),
    ("highlighted", "fg:#22d3ee bold"),
    ("selected", "fg:#c084fc bold"),
    ("answer", "fg:#22d3ee bold"),
    ("instruction", "fg:#6b7280 italic"),
])


def _safe(preferred: str, fallback: str) -> str:
    return preferred if _console_can_encode(preferred) else fallback


class ZenploaderError(Exception):
    """Raised for user-facing, recoverable errors."""


class Cancelled(Exception):
    """Raised when the user aborts an interactive prompt."""


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def _console_can_encode(sample: str) -> bool:
    enc = CONSOLE.encoding or "utf-8"
    try:
        sample.encode(enc)
        return True
    except (UnicodeEncodeError, LookupError):
        return False


def _human_size(num: int) -> str:
    size = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _icons() -> tuple[str, str]:
    """Return (folder, file) markers the terminal can actually render."""
    if _console_can_encode("📁📄"):
        return "📁", "📄"
    return "[D]", "[F]"


# --------------------------------------------------------------------------- #
# Branding and animation
# --------------------------------------------------------------------------- #
def _render_banner(highlight: int | None) -> Align:
    """Build the gradient banner, with a bright shimmer centred on `highlight`."""
    text = Text(justify="left")
    for row, line in enumerate(BANNER_LINES):
        base = BANNER_GRADIENT[row]
        for col, char in enumerate(line):
            if char == " ":
                text.append(" ")
                continue
            if highlight is not None and 0 <= highlight - col < 3:
                style = "bold white"
            elif highlight is not None and 0 <= highlight - col < 7:
                style = "bold #e0f2fe"
            else:
                style = base
            text.append(char, style=style)
        if row != len(BANNER_LINES) - 1:
            text.append("\n")
    return Align.center(text)


def _subtitle() -> Align:
    line = Text("Zendesk upload CDN", style="italic dim")
    line.append("  ·  ", style="dim")
    line.append(f"v{VERSION}", style="cyan")
    return Align.center(line)


def show_banner(animate: bool = True) -> None:
    """Print the banner, with a left-to-right shimmer when the terminal allows."""
    if not CONSOLE.is_terminal:
        return
    if not _console_can_encode("".join(BANNER_LINES)):
        CONSOLE.print(
            Panel(Align.center(Text("Z E N P L O A D E R", style="bold cyan")),
                  subtitle=f"Zendesk upload CDN · v{VERSION}", border_style="cyan")
        )
        return

    if animate:
        width = max(len(line) for line in BANNER_LINES)
        with Live(_render_banner(None), console=CONSOLE, refresh_per_second=60) as live:
            for highlight in range(-6, width + 7, 2):
                live.update(_render_banner(highlight))
                time.sleep(0.012)
            live.update(_render_banner(None))
    else:
        CONSOLE.print(_render_banner(None))

    CONSOLE.print(_subtitle())
    CONSOLE.print(Rule(style="cyan"))


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
def load_config(path: Path) -> dict:
    """Load and minimally validate the JSON config."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            cfg = json.load(fh)
    except FileNotFoundError as exc:
        raise ZenploaderError(f"Config file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ZenploaderError(f"Config file is not valid JSON ({path}): {exc}") from exc

    if not cfg.get("sites"):
        raise ZenploaderError("Config has no 'sites' entries.")
    return cfg


def valid_sites(cfg: dict) -> list[dict]:
    return [s for s in cfg["sites"] if "name" in s and "url" in s]


def save_config(path: Path, cfg: dict) -> None:
    """Write the config back to disk, preserving its 2-space style."""
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
    except OSError as exc:
        raise ZenploaderError(f"Could not save config {path}: {exc}") from exc


def animations_enabled(cfg: dict, args: argparse.Namespace) -> bool:
    pref = cfg.get("settings", {}).get("animations", True)
    return bool(pref) and not args.quiet and not args.no_anim


# --------------------------------------------------------------------------- #
# Interactive pickers (terminal UI)
# --------------------------------------------------------------------------- #
def menu_select(message: str, choices: list, *, search: bool = False, instruction: str | None = None):
    """Standardised arrow-key select. Raises Cancelled on abort."""
    answer = questionary.select(
        message,
        choices=choices,
        style=QSTYLE,
        qmark=_safe("›", ">"),
        pointer=_safe("❯", ">"),
        instruction=instruction,
        use_search_filter=search,
        use_jk_keys=not search,
    ).ask()
    if answer is None:
        raise Cancelled()
    return answer


def ask_text(message: str, *, default: str = "", multiline: bool = False,
             validate=None) -> str:
    answer = questionary.text(
        message,
        default=default,
        multiline=multiline,
        validate=validate,
        style=QSTYLE,
        qmark=_safe("›", ">"),
    ).ask()
    if answer is None:
        raise Cancelled()
    return answer


def pick_site(cfg: dict) -> str:
    """Arrow-key picker over the configured sites, returns the chosen URL."""
    sites = valid_sites(cfg)
    if not sites:
        raise ZenploaderError("No valid sites (need 'name' and 'url') in config.")

    choices = [questionary.Choice(title=s["name"], value=s["url"]) for s in sites]
    return menu_select(
        "Upload target", choices, search=True,
        instruction="(type to search, ↑↓ to move, Enter to pick)",
    )


def pick_file(start: Path) -> Path:
    """Pick a file via the native OS dialog, falling back to the terminal browser."""
    chosen = _native_file_dialog(start)
    if chosen is not None:
        return chosen
    return _browse_file(start)


def _native_file_dialog(start: Path) -> Path | None:
    """Open the OS file-open dialog. Returns None if no GUI is available."""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception:
        return None  # tkinter not installed

    try:
        root = tk.Tk()
    except Exception:
        return None  # no display / headless

    if CONSOLE.is_terminal:
        CONSOLE.print("[dim]Opening file chooser...[/dim]")
    try:
        root.withdraw()
        root.attributes("-topmost", True)
        root.update()
        selected = filedialog.askopenfilename(
            parent=root,
            title="Select a file to upload",
            initialdir=str(start),
        )
    finally:
        root.destroy()

    if not selected:  # dialog cancelled or closed
        raise Cancelled()
    return Path(selected)


def _browse_file(start: Path) -> Path:
    """A navigable terminal file browser. Enter folders, pick a file, '..' goes up."""
    folder_icon, file_icon = _icons()
    current = start.resolve()

    while True:
        try:
            entries = sorted(
                current.iterdir(),
                key=lambda p: (p.is_file(), p.name.lower()),
            )
        except PermissionError:
            ERR.print(f"[red]Permission denied:[/red] {current}")
            entries = []

        choices: list[questionary.Choice] = []
        if current.parent != current:
            choices.append(questionary.Choice(title=f"{folder_icon} ..", value=("up", None)))
        for entry in entries:
            if entry.is_dir():
                choices.append(
                    questionary.Choice(title=f"{folder_icon} {entry.name}/", value=("dir", entry))
                )
        for entry in entries:
            if entry.is_file():
                try:
                    size = _human_size(entry.stat().st_size)
                except OSError:
                    size = "?"
                choices.append(
                    questionary.Choice(
                        title=f"{file_icon} {entry.name}  ({size})", value=("file", entry)
                    )
                )

        kind, target = menu_select(
            f"Select a file  —  {current}", choices, search=True,
            instruction="(type to search, ↑↓ to move, Enter to open/pick)",
        )
        if kind == "up":
            current = current.parent
        elif kind == "dir":
            current = target
        else:
            return target


# --------------------------------------------------------------------------- #
# Inference
# --------------------------------------------------------------------------- #
def guess_content_type(path: Path) -> str:
    ctype, _ = mimetypes.guess_type(path.name)
    return ctype or "application/octet-stream"


def resolve_content_type(args: argparse.Namespace) -> str:
    if args.content_type:
        return args.content_type
    if args.file:
        return guess_content_type(Path(args.file))
    return "text/plain"  # plain-text upload


def resolve_filename(args: argparse.Namespace) -> str:
    if args.name:
        return args.name.strip()
    if args.file:
        return Path(args.file).name
    return "paste.txt"  # plain-text upload


# --------------------------------------------------------------------------- #
# Upload
# --------------------------------------------------------------------------- #
def read_payload(args: argparse.Namespace) -> bytes:
    """Resolve the upload payload from --file or --plain."""
    if args.file is not None:
        return read_file_bytes(Path(args.file))
    return args.plain.encode("utf-8")


def read_file_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except FileNotFoundError as exc:
        raise ZenploaderError(f"File not found: {path}") from exc
    except OSError as exc:
        raise ZenploaderError(f"Could not read file {path}: {exc}") from exc


def zenpload(url: str, filename: str, content_type: str, data: bytes) -> dict:
    """POST the payload to the Zendesk uploads endpoint and return the JSON body."""
    endpoint = f"{url}?filename={quote(filename)}"
    try:
        resp = requests.post(
            endpoint,
            headers={
                "Content-Type": content_type,
                "User-Agent": "zenploader/1.0 (+https://github.com/spinfal/zenploader)",
            },
            data=data,
            timeout=REQUEST_TIMEOUT,
        )
    except requests.exceptions.MissingSchema as exc:
        raise ZenploaderError(f"Invalid URL '{url}' - check the formatting.") from exc
    except requests.exceptions.ConnectTimeout as exc:
        raise ZenploaderError("Connection timed out.") from exc
    except requests.exceptions.ConnectionError as exc:
        raise ZenploaderError(f"Connection error: {exc}") from exc
    except requests.exceptions.RequestException as exc:
        raise ZenploaderError(f"Request failed: {exc}") from exc

    if resp.status_code != 201:
        raise ZenploaderError(
            f"Upload failed (HTTP {resp.status_code}). Response: {resp.text[:500]}"
        )

    try:
        return resp.json()
    except json.JSONDecodeError as exc:
        raise ZenploaderError("Upload succeeded but the response was not valid JSON.") from exc


def upload_with_progress(animate: bool, **kwargs) -> dict:
    """Run the upload behind a pulsing progress bar (plain spinner if disabled)."""
    if not animate or not CONSOLE.is_terminal:
        with CONSOLE.status("[cyan]Uploading...[/cyan]"):
            return zenpload(**kwargs)

    progress = Progress(
        SpinnerColumn(spinner_name="dots"),
        TextColumn("[bold cyan]Uploading[/bold cyan]"),
        BarColumn(bar_width=32, pulse_style="cyan", style="grey37"),
        TimeElapsedColumn(),
        console=CONSOLE,
        transient=True,
    )
    with progress:
        progress.add_task("upload", total=None)  # indeterminate -> pulsing bar
        return zenpload(**kwargs)


def _format_expires(raw: str) -> str:
    """Render a Zendesk ISO-8601 expiry in the user's local time zone.

    Falls back to the original string if it cannot be parsed.
    """
    try:
        # Zendesk returns UTC with a trailing "Z", which fromisoformat
        # only accepts natively on Python 3.11+, so normalise it first.
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return raw
    local = parsed.astimezone()
    stamp = local.strftime("%b %d, %Y at %I:%M %p").replace(" 0", " ")
    tz = local.strftime("%Z")
    return f"{stamp} {tz}".strip() if tz else stamp


def show_result(body: dict, animate: bool = True) -> None:
    try:
        upload = body["upload"]
        expires = _format_expires(upload["expires_at"])
        file_url = upload["attachments"][0]["mapped_content_url"]
    except (KeyError, IndexError) as exc:
        raise ZenploaderError(
            f"Unexpected response shape: {json.dumps(body)[:500]}"
        ) from exc

    if animate and CONSOLE.is_terminal:
        check = "✓" if _console_can_encode("✓") else "OK"
        with Live(console=CONSOLE, refresh_per_second=30) as live:
            for step in range(1, 4):
                live.update(Text(f"  {check} " + "." * step, style="bold green"))
                time.sleep(0.08)
            live.update(Text(f"  {check} Upload complete", style="bold green"))

    CONSOLE.print(
        Panel(
            f"[bold green]URL:[/bold green] [link={file_url}]{file_url}[/link]\n"
            f"[bold]Expires at:[/bold] {expires}",
            title="Upload complete",
            border_style="green",
            padding=(1, 2),
        )
    )


def show_summary(filename: str, size: int, content_type: str, site: str) -> None:
    if not CONSOLE.is_terminal:
        return
    text = Text()
    text.append("  ")
    text.append(filename, style="bold")
    text.append(f"  ({_human_size(size)} · {content_type})", style="dim")
    text.append("  →  ", style="dim")
    text.append(site, style="cyan")
    CONSOLE.print(text)


def perform_upload(args: argparse.Namespace, cfg: dict, data: bytes,
                   filename: str, content_type: str) -> None:
    """Shared tail of every upload: pick target, send, show result."""
    filename = filename.strip()
    if not filename:
        raise ZenploaderError("A filename is required.")
    if len(filename) > MAX_FILENAME_LEN:
        raise ZenploaderError(f"Filename too long (max {MAX_FILENAME_LEN} characters).")

    if args.url:
        url = args.url
    elif CONSOLE.is_terminal:
        url = pick_site(cfg)
    else:
        raise ZenploaderError("No --url given and no terminal for the site picker.")

    animate = animations_enabled(cfg, args)
    show_summary(filename, len(data), content_type, url)
    body = upload_with_progress(
        animate, url=url, filename=filename, content_type=content_type, data=data
    )
    show_result(body, animate=animate)


# --------------------------------------------------------------------------- #
# Menu actions
# --------------------------------------------------------------------------- #
def ask_confirm(message: str, default: bool = False) -> bool:
    answer = questionary.confirm(
        message, default=default, style=QSTYLE, qmark=_safe("›", ">")
    ).ask()
    if answer is None:
        raise Cancelled()
    return answer


def _require(label: str):
    def validator(value: str):
        return True if value.strip() else f"{label} is required."
    return validator


def _validate_url(value: str):
    value = value.strip()
    if value.startswith(("http://", "https://")) and len(value) > 8:
        return True
    return "Enter a full URL starting with http:// or https://"


def action_upload(args: argparse.Namespace, cfg: dict) -> None:
    mode = menu_select("What do you want to upload?", [
        questionary.Choice(title="A file", value="file"),
        questionary.Choice(title="Text (uploaded as a .txt file)", value="text"),
    ])

    if mode == "file":
        path = pick_file(Path.cwd())
        data = read_file_bytes(path)
        default_name = path.name
        origin = path
    else:
        content = ask_text("Enter the text to upload", multiline=True)
        data = content.encode("utf-8")
        default_name = "untitled.txt"
        origin = None

    filename = ask_text("Filename", default=default_name, validate=_require("Filename")).strip()
    if mode == "text" and not Path(filename).suffix:
        filename += ".txt"

    if args.content_type:
        content_type = args.content_type
    elif mode == "text":
        content_type = "text/plain"
    else:
        content_type = guess_content_type(Path(filename))
        if content_type == "application/octet-stream" and origin is not None:
            content_type = guess_content_type(origin)

    perform_upload(args, cfg, data, filename, content_type)


def action_add_entry(cfg: dict, config_path: Path) -> None:
    name = ask_text("Site name", validate=_require("Name")).strip()
    url = ask_text("Upload URL", default="https://", validate=_validate_url).strip()
    cfg.setdefault("sites", []).append({"name": name, "url": url})
    save_config(config_path, cfg)
    CONSOLE.print(f"[green]{_safe('✓', '+')} Added[/green] [bold]{name}[/bold]")


def action_settings(cfg: dict, config_path: Path) -> None:
    while True:
        settings = cfg.setdefault("settings", {})
        anim = settings.get("animations", True)
        choice = menu_select("Settings", [
            questionary.Choice(title=f"Animations: {'on' if anim else 'off'}", value="anim"),
            questionary.Choice(title="Remove a site entry", value="remove"),
            questionary.Choice(title="Back", value="back"),
        ])
        if choice == "back":
            return
        if choice == "anim":
            settings["animations"] = not anim
            save_config(config_path, cfg)
            CONSOLE.print(f"[dim]Animations {'disabled' if anim else 'enabled'}.[/dim]")
        elif choice == "remove":
            _remove_entry(cfg, config_path)


def _remove_entry(cfg: dict, config_path: Path) -> None:
    sites = valid_sites(cfg)
    if not sites:
        CONSOLE.print("[yellow]No site entries to remove.[/yellow]")
        return
    choices = [questionary.Choice(title=s["name"], value=s["url"]) for s in sites]
    choices.append(questionary.Choice(title="(cancel)", value="__cancel__"))
    url = menu_select("Remove which site?", choices, search=True)
    if url == "__cancel__":
        return
    target = next((s for s in cfg["sites"] if s.get("url") == url), None)
    if target and ask_confirm(f"Remove '{target['name']}'?", default=False):
        cfg["sites"].remove(target)
        save_config(config_path, cfg)
        CONSOLE.print(f"[green]Removed[/green] {target['name']}")


def main_menu(args: argparse.Namespace, cfg: dict) -> int:
    config_path = Path(args.config)
    while True:
        try:
            choice = menu_select("Main menu", [
                questionary.Choice(title="Upload", value="upload"),
                questionary.Choice(title="Add new site entry", value="add"),
                questionary.Choice(title="Settings", value="settings"),
                questionary.Choice(title="Exit", value="exit"),
            ])
        except Cancelled:
            return 0

        if choice == "exit":
            return 0

        try:
            if choice == "upload":
                action_upload(args, cfg)
            elif choice == "add":
                action_add_entry(cfg, config_path)
            elif choice == "settings":
                action_settings(cfg, config_path)
        except Cancelled:
            CONSOLE.print("[yellow]Cancelled.[/yellow]")

        CONSOLE.print(Rule(style="grey37"))


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="zenploader",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Upload files to Zendesk help-desk upload APIs and get a public CDN URL.\n"
            "Run with no flags for a terminal UI, or pass flags to script it."
        ),
    )
    src = parser.add_mutually_exclusive_group()
    src.add_argument("-f", "--file", metavar="PATH", help="File to upload.")
    src.add_argument("-p", "--plain", metavar="TEXT", help="Upload plain text content.")

    parser.add_argument(
        "-c", "--config", metavar="PATH", default=str(DEFAULT_CONFIG),
        help="Path to an alternative config file.",
    )
    parser.add_argument(
        "-u", "--url", metavar="URL",
        help="Upload endpoint URL (skips the site picker).",
    )
    parser.add_argument(
        "-t", "--content-type", metavar="MIME",
        help="Override the auto-detected Content-Type.",
    )
    parser.add_argument(
        "-n", "--name", metavar="NAME",
        help="Override the filename used in the upload URL.",
    )
    parser.add_argument(
        "-l", "--list", action="store_true",
        help="List the configured sites and exit.",
    )
    parser.add_argument(
        "--no-anim", action="store_true",
        help="Show the banner but skip animations.",
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true",
        help="Suppress the banner and animations.",
    )
    return parser


def run(args: argparse.Namespace) -> int:
    cfg = load_config(Path(args.config))

    if args.list:
        for site in valid_sites(cfg):
            CONSOLE.print(f"[green]*[/green] {site['name']}  [dim]{site['url']}[/dim]")
        return 0

    # A source given on the command line means a one-shot, scripted upload.
    if args.file is not None or args.plain is not None:
        data = read_payload(args)
        content_type = resolve_content_type(args)
        filename = resolve_filename(args)
        perform_upload(args, cfg, data, filename, content_type)
        return 0

    # Otherwise, run the interactive app.
    if not CONSOLE.is_terminal:
        raise ZenploaderError(
            "The interactive menu needs a terminal. Use --file or --plain to script uploads."
        )

    CONSOLE.clear()
    if not args.quiet:
        show_banner(animate=animations_enabled(cfg, args))
    return main_menu(args, cfg)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except ZenploaderError as exc:
        ERR.print(f"[red]Error:[/red] {exc}")
        return 1
    except (Cancelled, KeyboardInterrupt):
        ERR.print("\n[yellow]Cancelled.[/yellow]")
        return 130


if __name__ == "__main__":
    sys.exit(main())
