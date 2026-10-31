# zenploader

Zendesk help desks expose an unauthenticated `/api/v2/uploads.json` endpoint
that is normally used to attach files to support tickets. zenploader posts a
file (or some plain text) to one of those endpoints and hands you back the
public, CDN-backed URL of the upload — effectively a free file host.

Uploads are temporary. The response includes an `expires_at` timestamp.

## Install

Requires Python 3.9+.

```bash
pip install -r requirements.txt
```

Or install it as a command:

```bash
pip install .
```

## Usage

Run with no flags for the interactive app. You get a main menu:

- **Upload** - choose a file (via your OS file-open dialog) or type some text
  (uploaded as a `.txt`), give it a filename, then pick a target from the
  searchable site list. The Content-Type is detected automatically.
- **Add new site entry** - add a new upload target (name + URL) to the config.
- **Settings** - toggle the animations, or remove a site entry.
- **Exit**.

```bash
python zenploader.py
```

Arrow keys move, Enter selects, and most lists are searchable - just start
typing. Ctrl-C backs out of an action.

Or drive it entirely from flags for scripting:

```bash
python zenploader.py -f ./cat.png            # content type + name auto-detected
python zenploader.py -p "hello world"        # quick plain-text upload
python zenploader.py -f big.zip -u https://support.example.com/api/v2/uploads.json
```

### Flags

| Flag | Description |
| --- | --- |
| `-f`, `--file PATH` | File to upload (skips the file dialog). |
| `-p`, `--plain TEXT` | Upload plain text content instead of a file. |
| `-u`, `--url URL` | Upload endpoint URL (skips the site picker). |
| `-t`, `--content-type MIME` | Override the auto-detected Content-Type. |
| `-n`, `--name NAME` | Override the filename used in the upload URL. |
| `-c`, `--config PATH` | Use an alternative config file. |
| `-l`, `--list` | List the configured sites and exit. |
| `--no-anim` | Show the banner but skip the animations. |
| `-q`, `--quiet` | Suppress the banner and animations entirely. |

The Content-Type and filename are inferred from the file unless you override
them with `-t` / `-n`. The interactive pickers, banner, and progress bar only
appear in a real terminal - output is kept clean when piped or redirected.

## Config

`config.json` holds the list of upload targets (`sites`) and the menu of
`content-types`. Add a site by appending an object with a `name` and `url`:

```json
{ "name": "example support cdn", "url": "https://support.example.com/api/v2/uploads.json" }
```

## Disclaimer

This tool is for educational purposes. Only upload content you are allowed to
upload, and respect the terms of service of the help desks involved.
