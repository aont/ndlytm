# ndl-webui

A small local web app that downloads a playlist of `.m4a` tracks, rewrites MP4 metadata, and returns them as a single ZIP file.

## What it does

- Accepts playlist JSON from the browser UI (`/`)
- Downloads each track using the provided `Cookie` and `BaseURL`
- Tags each file with title/artist/album/track number
- Packages everything into `tracks.zip`
- Streams job progress and logs while processing

## Requirements

- Python 3.9+
- `aiohttp`
- `mutagen`

Install dependencies:

```bash
pip install aiohttp mutagen
```

## Run

```bash
python3 server.py --port 8080
```

The app starts on `http://127.0.0.1:8080`.

`--port` can be changed to run the backend on a different port.

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

- `POST /start` — create a processing job
- `GET /progress/{job_id}` — get progress + recent logs
- `GET /download/{job_id}` — download resulting ZIP once job is complete

## Notes

- Tracks are currently zipped with original filenames derived from the source `.mp4` path.
- Temporary files are used during tagging and then removed.
