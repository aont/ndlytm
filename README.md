# ndl

A small local web app that downloads a playlist of `.m4a` tracks, rewrites MP4 metadata, and saves the processed files on the server.

## What it does

- Accepts playlist JSON from the browser UI (`/`)
- Downloads each track using the provided `Cookie` and `BaseURL`
- Tags each file with title/artist/album/track number
- Optionally embeds album art from a top-level `AlbumArt` URL
- Saves each processed track to a `catalogid` subfolder in the server-side output directory
- Streams progress and logs for the currently running job

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
python3 server.py --port 8080 --output-dir downloads
```

The app starts on `http://127.0.0.1:8080`.

- `--port` can be changed to run the backend on a different port.
- `--output-dir` controls where processed `.m4a` files are saved. It defaults to `downloads`. Each job saves files under a sanitized subfolder named for the payload `catalogid` (or the first track album `catalogid`).

If you host frontend and backend on different domains, set **Backend Base URI** in the UI (for example, `https://api.example.com`). The value is persisted in browser `localStorage`.

## Input JSON format

Paste JSON into the UI in this shape:

```json
{
  "Cookie": "session=...",
  "BaseURL": "https://example.com",
  "AlbumArt": "https://cdn.example.com/cover.jpg",
  "catalogid": "catalog-123",
  "PlayListsTracks": [
    {
      "m4a": "/path/to/file.mp4",
      "workName": "Work",
      "title": "Track",
      "artist": "Artist",
      "album": {
        "catalogid": "catalog-123",
        "cataloguename": "Album Title（Album Artist）"
      }
    }
  ]
}
```

## Bookmarklet helper

`bookmarklet.js` builds a URL containing prefilled JSON (`Cookie`, `BaseURL`, `PlayListsTracks`, `AlbumArt`) and opens this app.

The bookmarklet explicitly reads the album image (`#album-link > img`) from the source page, stores it in `AlbumArt`, and passes it along in the generated payload.

If `AlbumArt` is provided in the JSON payload, the backend downloads that image once per job and writes it into each tagged `.m4a` file using Mutagen before saving.

## Endpoints

- `POST /start` — start a save job
- `GET /progress/{job_id}` — get progress + recent logs
- `GET /progress-stream/{job_id}` — stream progress events

## Notes

- Files are written to a `catalogid` subfolder in the configured output directory after tagging. Existing filenames are not overwritten; a numeric suffix is added instead.
- If the payload does not include `catalogid` at the top level or under any track `album`, files are saved under `unknown-catalog`.
