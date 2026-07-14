# ndl

A small local web app that downloads a playlist of `.m4a` tracks, rewrites MP4 metadata, transfers the processed files to the browser as an uncompressed zip, and deletes the generated server-side track files after transfer.

## What it does

- Accepts playlist JSON from the browser UI (`/`)
- Downloads each track using the provided `Cookie` and `BaseURL`
- Caches the downloaded raw, untagged audio files on the filesystem before metadata is written
- Tags each file with title/artist/album/track number
- Optionally embeds album art from a top-level `AlbumArt` URL
- Temporarily saves each processed track to a server-side output directory
- Reuses cached raw audio on later jobs when the same track URL is requested
- Streams progress and logs for the currently running job
- Packages completed jobs as an uncompressed `.zip` for browser download
- Deletes generated `.m4a` files from the server after the zip has been transferred to the frontend

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
python3 server.py --port 8080 --output-dir downloads --raw-cache-dir raw-cache
```

The app starts on `http://127.0.0.1:8080`.

- `--port` can be changed to run the backend on a different port.
- `--output-dir` controls where processed `.m4a` files are staged before zip transfer. It defaults to `downloads`.
- `--raw-cache-dir` controls where downloaded, untagged source audio files are cached before Mutagen writes tags. It defaults to `raw-cache`.

If you host frontend and backend on different domains, set **Backend Base URI** in the UI (for example, `https://api.example.com`). The value is persisted in browser `localStorage`.

## Input JSON format

Paste JSON into the UI in this shape:

```json
{
  "Cookie": "session=...",
  "BaseURL": "https://example.com",
  "AlbumArt": "https://cdn.example.com/cover.jpg",
  "PlayListsTracks": [
    {
      "album": {
        "catalogue_link": "/album/catalogueid",
        "catalogueid": "catalogueid",
        "cataloguename": "Album Title（Album Artist）",
        "catlabelid": "catlabelid",
        "labeldisplayname": "Label Display Name"
      },
      "artist": "Artist",
      "composer": "Composer",
      "composerShort": "Composer Short",
      "dbfilename": "dbfilename",
      "length": "00:05:43",
      "m4a": "/foobar?path=/media/aacstorage/aac320k/catlabelid/dbfilename_full_320.mp4&tid=406742",
      "title": "Track",
      "trackDesc": null,
      "trackid": 12345,
      "trackno": 1,
      "workName": "Work"
    }
  ]
}
```

Top-level fields:

- `Cookie`: cookie header value used when downloading protected track files.
- `BaseURL`: origin prepended to each track's `m4a` path.
- `AlbumArt`: optional image URL that is downloaded once and embedded in every saved track.
- `PlayListsTracks`: array of track objects from the source playlist.

Track fields used by the backend are `m4a`, `workName`, `title`, `artist`, and `album.cataloguename`. The other fields shown above are accepted from the source playlist and preserved in the expected payload shape, but are not currently used when downloading or tagging files.

## Bookmarklet helper

`bookmarklet.js` builds a URL containing prefilled JSON (`Cookie`, `BaseURL`, `PlayListsTracks`, `AlbumArt`) and opens this app.

The bookmarklet explicitly reads the album image (`#album-link > img`) from the source page, stores it in `AlbumArt`, and passes it along in the generated payload.

If `AlbumArt` is provided in the JSON payload, the backend downloads that image once per job and writes it into each tagged `.m4a` file using Mutagen before saving.

## Endpoints

- `POST /start` — start a save job
- `GET /progress/{job_id}` — get progress + recent logs
- `GET /progress-stream/{job_id}` — stream progress events
- `GET /download/{job_id}` — return completed tracks as an uncompressed zip and delete the generated server-side `.m4a` files after the response body is prepared

## Notes

- Raw downloaded audio is cached before tagging using a URL-derived hash plus the original filename. Existing cached raw files are reused without re-downloading.
- Files are written to the configured output directory after tagging. Existing filenames are not overwritten; a numeric suffix is added instead.
- Completed jobs can be downloaded once from the frontend. The browser stores the transferred zip as a blob URL, and the backend deletes the generated `.m4a` files after preparing that transfer.
