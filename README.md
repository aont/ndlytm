# ndlytm

A small local web app that downloads a playlist of `.m4a` tracks, rewrites MP4 metadata, and uploads them to YouTube Music via `ytmusicapi`.

## What it does

- Accepts playlist JSON from the browser UI (`/`)
- Downloads each track using the provided `Cookie` and `BaseURL`
- Tags each file with title/artist/album/track number
- Uploads each processed track to YouTube Music with `ytmusicapi`
- Streams job progress and logs while processing

## Requirements

- Python 3.9+
- `aiohttp`
- `mutagen`
- `ytmusicapi`

Install dependencies:

```bash
pip install aiohttp mutagen ytmusicapi
```

## Run

```bash
python3 server.py --port 8080 --ytmusic-browser-auth /path/to/browser.json
```

The app starts on `http://127.0.0.1:8080`.

- `--port` can be changed to run the backend on a different port.
- `--ytmusic-browser-auth` should point to a `browser.json` generated for `ytmusicapi` authentication.

If you host frontend and backend on different domains, set **Backend Base URI** in the UI (for example, `https://api.example.com`). The value is persisted in browser `localStorage`.

## Input JSON format

Paste JSON into the UI in this shape:

```json
{
  "Cookie": "session=...",
  "BaseURL": "https://example.com",
  "PlayListsTracks": [
    {
      "m4a": "/path/to/file.mp4",
      "workName": "Work",
      "title": "Track",
      "artist": "Artist",
      "album": {
        "cataloguename": "Album Title（Album Artist）"
      }
    }
  ]
}
```

## Bookmarklet helper

`bookmarklet.js` builds a URL containing prefilled JSON (`Cookie`, `BaseURL`, `PlayListsTracks`) and opens this app.

## Endpoints

- `POST /start` — create an upload job
- `GET /progress/{job_id}` — get progress + recent logs
- `GET /progress-stream/{job_id}` — stream progress events

## Notes

- Files are stored in temporary files only while tagging/uploading and then removed.
- The server must be started with a valid `--ytmusic-browser-auth` path before running jobs.
