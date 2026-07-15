#!/usr/bin/env python3

import asyncio
import argparse
import hashlib
import json
import re
import uuid
import logging
import tempfile
import zipfile
from pathlib import Path

import aiohttp
from aiohttp import web
import mutagen.mp4


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

mp4_fn_pat = re.compile(r"/([^/]+)\.mp4")
catalogname_patterns = (
    re.compile(r"^(?P<title>.+?)（(?P<artist>.+?)）$"),
    re.compile(r"^(?P<title>.+?)\((?P<artist>.+?)\)$"),
)

jobs = {}
output_dir = None
raw_cache_dir = None


@web.middleware
async def cors_middleware(request, handler):
    if request.method == "OPTIONS":
        response = web.Response(status=204)
    else:
        response = await handler(request)

    origin = request.headers.get("Origin")
    if origin:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"

    response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


class JobState:
    def __init__(self):
        self.progress = 0
        self.total = 0
        self.logs = []
        self.done = False
        self.error = None
        self.saved = 0
        self.status = "queued"
        self.files = []
        self.downloaded = False

    def snapshot(self):
        return {
            "progress": self.progress,
            "total": self.total,
            "done": self.done,
            "error": self.error,
            "saved": self.saved,
            "status": self.status,
            "download_ready": self.done and not self.error and not self.downloaded and bool(self.files),
            "downloaded": self.downloaded,
            "logs": self.logs[-200:],
        }

    def log(self, message):
        logging.info(message)
        self.logs.append(message)


def sanitize_filename(filename):
    sanitized = re.sub(r'[\\/:*?"<>|]+', "_", filename).strip()
    return sanitized or "track.m4a"


def build_track_title(track, include_composer=False):
    work_name = track["workName"]
    title = track["title"]

    if title == "":
        track_title = work_name
    elif work_name == "":
        track_title = title
    else:
        track_title = title + " - " + work_name

    composer = track.get("composer", "")
    if include_composer and composer:
        return track_title + " - " + composer

    return track_title


def match_catalogue_name(value):
    catalogue_name = str(value or "").strip()

    for pattern in catalogname_patterns:
        match = pattern.fullmatch(catalogue_name)
        if match:
            return match

    return None


def parse_catalogue_name(value, fallback_artist=""):
    catalogue_name = str(value or "").strip()
    match = match_catalogue_name(catalogue_name)

    if match:
        return (
            match.group("title").strip(),
            match.group("artist").strip(),
        )

    return catalogue_name or "Unknown Album", fallback_artist


def playlist_has_multiple_composers(tracks):
    composers = {track.get("composer", "") for track in tracks}
    return len(composers) > 1


def cache_filename_for_track(url, filename):
    safe_name = sanitize_filename(filename)
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    return f"{digest}-{safe_name}"


def unique_output_path(directory, filename):
    directory = Path(directory)
    safe_name = sanitize_filename(filename)
    candidate = directory / safe_name

    if not candidate.exists():
        return candidate

    stem = candidate.stem
    suffix = candidate.suffix
    counter = 1
    while True:
        candidate = directory / f"{stem}-{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


async def process_job(job_id, payload):
    state = jobs[job_id]
    state.status = "running"

    if not output_dir:
        state.status = "failed"
        state.error = "Output directory is not configured"
        state.log("Job failed: Output directory is not configured")
        return

    try:
        cookie = payload["Cookie"]
        base_url = payload["BaseURL"]
        tracks = payload["PlayListsTracks"]
        album_art_url = payload.get("AlbumArt")
        album_art_cover = None

        state.total = len(tracks)
        include_composer_in_title = playlist_has_multiple_composers(tracks)
        state.log(f"Starting job {job_id} with {state.total} tracks")
        async with aiohttp.ClientSession() as session:
            if album_art_url:
                state.log(f"Downloading album art: {album_art_url}")
                async with session.get(album_art_url) as album_art_resp:
                    state.log(f"Album art response status={album_art_resp.status}")
                    album_art_resp.raise_for_status()
                    album_art_data = await album_art_resp.read()
                    state.log(f"Fetched album art bytes={len(album_art_data)}")

                album_art_format = mutagen.mp4.MP4Cover.FORMAT_JPEG
                lowered_album_art_url = album_art_url.lower()
                if lowered_album_art_url.endswith(".png"):
                    album_art_format = mutagen.mp4.MP4Cover.FORMAT_PNG

                album_art_cover = mutagen.mp4.MP4Cover(album_art_data, imageformat=album_art_format)

            for i, track in enumerate(tracks):
                track_num = i + 1
                state.log(f"Downloading track {track_num}/{state.total}")

                m4a_path = track["m4a"]
                match = mp4_fn_pat.search(m4a_path)
                if not match:
                    state.log(f"Invalid m4a path: {m4a_path}")
                    continue

                filename = match.group(1) + ".m4a"
                url = base_url + m4a_path

                cache_path = raw_cache_dir / cache_filename_for_track(url, filename)
                if cache_path.exists():
                    state.log(f"Using cached raw track: {cache_path.name}")
                    data = cache_path.read_bytes()
                    state.log(f"Loaded cached bytes={len(data)} for {filename}")
                else:
                    headers = {"Cookie": cookie}
                    state.log(f"Fetching URL: {url}")
                    async with session.get(url, headers=headers) as resp:
                        state.log(f"Track response status={resp.status} for {filename}")
                        resp.raise_for_status()
                        data = await resp.read()
                        state.log(f"Fetched bytes={len(data)} for {filename}")

                    temp_cache_path = cache_path.with_name(f".{cache_path.name}.{uuid.uuid4().hex}.tmp")
                    try:
                        temp_cache_path.write_bytes(data)
                        temp_cache_path.replace(cache_path)
                    finally:
                        temp_cache_path.unlink(missing_ok=True)
                    state.log(f"Cached raw track: {cache_path}")

                output_path = unique_output_path(output_dir, filename)
                output_path.write_bytes(data)

                try:
                    state.log(f"Tagging {output_path.name}")

                    audio = mutagen.mp4.MP4(output_path)

                    track_title = build_track_title(track, include_composer_in_title)
                    audio["\xa9nam"] = [track_title]
                    audio["\xa9ART"] = [track["artist"]]

                    composer = track.get("composer")
                    if composer:
                        audio["\xa9wrt"] = [composer]

                    album = track.get("album") or {}
                    catalogue_name = album.get("cataloguename")
                    if not match_catalogue_name(catalogue_name):
                        state.log(
                            f"Unrecognized cataloguename for track {track_num}: "
                            f"{catalogue_name!r}"
                        )
                    album_title, album_artist = parse_catalogue_name(
                        catalogue_name,
                        fallback_artist=track.get("artist", ""),
                    )

                    audio["\xa9alb"] = [album_title]
                    if album_artist:
                        audio["aART"] = [album_artist]
                    audio["trkn"] = [(track_num, state.total)]
                    if album_art_cover:
                        audio["covr"] = [album_art_cover]

                    audio.save()

                    state.saved += 1
                    state.files.append(output_path)
                    state.log(f"Saved {output_path}")
                except Exception:
                    if output_path.exists():
                        output_path.unlink()
                    raise

                state.progress = track_num
                state.log(f"Finished {output_path.name}")

        state.done = True
        state.status = "completed"
        state.log(f"Job completed successfully (saved={state.saved})")
    except Exception as exc:
        state.status = "failed"
        state.error = str(exc)
        state.log(f"Job failed: {exc}")
        logging.exception("Unhandled exception during job %s", job_id)


async def on_startup(app):
    app["queue_worker_task"] = asyncio.create_task(queue_worker(app))


async def on_cleanup(app):
    worker_task = app.get("queue_worker_task")
    if worker_task and not worker_task.done():
        worker_task.cancel()

    running_jobs = [task for task in app.get("job_tasks", set()) if not task.done()]
    for task in running_jobs:
        task.cancel()
    if running_jobs:
        await asyncio.gather(*running_jobs, return_exceptions=True)

    if worker_task:
        await asyncio.gather(worker_task, return_exceptions=True)


async def queue_worker(app):
    queue = app["job_queue"]
    while True:
        job_id, payload = await queue.get()
        state = jobs.get(job_id)
        if not state:
            queue.task_done()
            continue

        state.log(f"Dequeued job {job_id} for processing")

        task = asyncio.create_task(process_job(job_id, payload))
        app_tasks = app["job_tasks"]
        app_tasks.add(task)
        task.add_done_callback(app_tasks.discard)
        await task
        queue.task_done()


async def start_job(request):
    payload = await request.json()

    job_id = str(uuid.uuid4())

    state = JobState()
    jobs[job_id] = state
    logging.info("Received /start request, assigned job_id=%s", job_id)

    state.log(f"Queued job {job_id}")
    queue = request.app["job_queue"]
    await queue.put((job_id, payload))

    return web.json_response({"job_id": job_id, "status": state.status})


def build_download_name(job_id):
    return sanitize_filename(f"ndl-{job_id}.zip")


def remove_job_files(state):
    removed = 0
    for file_path in list(state.files):
        path = Path(file_path)
        if path.exists():
            path.unlink()
            removed += 1
    state.files = []
    return removed


async def download_job(request):
    job_id = request.match_info["job_id"]
    state = jobs.get(job_id)

    if not state:
        return web.json_response({"error": "Invalid job ID"}, status=404)

    if state.error:
        return web.json_response({"error": state.error}, status=409)

    if not state.done:
        return web.json_response({"error": "Job is not complete yet"}, status=409)

    available_files = [Path(file_path) for file_path in state.files if Path(file_path).exists()]
    if not available_files:
        return web.json_response({"error": "Job files are no longer available"}, status=410)

    download_name = build_download_name(job_id)

    temp_file = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    temp_path = Path(temp_file.name)
    temp_file.close()

    try:
        with zipfile.ZipFile(temp_path, mode="w", compression=zipfile.ZIP_STORED) as archive:
            used_names = set()
            for file_path in available_files:
                arcname = file_path.name
                if arcname in used_names:
                    stem = file_path.stem
                    suffix = file_path.suffix
                    counter = 1
                    while f"{stem}-{counter}{suffix}" in used_names:
                        counter += 1
                    arcname = f"{stem}-{counter}{suffix}"
                used_names.add(arcname)
                archive.write(file_path, arcname=arcname)

        zip_data = temp_path.read_bytes()
        temp_path.unlink(missing_ok=True)
        removed = remove_job_files(state)
        state.downloaded = True
        state.log(f"Transferred {download_name}; deleted {removed} generated m4a files")

        return web.Response(
            body=zip_data,
            headers={
                "Content-Disposition": f'attachment; filename="{download_name}"',
                "Content-Type": "application/zip",
                "Cache-Control": "no-store",
            },
        )
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


async def get_progress(request):
    job_id = request.match_info["job_id"]
    state = jobs.get(job_id)

    if not state:
        return web.json_response({"error": "Invalid job ID"}, status=404)

    return web.json_response(state.snapshot())


async def stream_progress(request):
    job_id = request.match_info["job_id"]
    state = jobs.get(job_id)
    if not state:
        return web.Response(status=404, text="Invalid job ID")

    origin = request.headers.get("Origin")

    response = web.StreamResponse(
        status=200,
        reason="OK",
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
    if origin:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
    await response.prepare(request)

    last_payload = None
    try:
        while True:
            payload = json.dumps(state.snapshot(), ensure_ascii=False)
            if payload != last_payload:
                await response.write(f"event: progress\ndata: {payload}\n\n".encode("utf-8"))
                last_payload = payload

            if state.done or state.error:
                break

            await asyncio.sleep(1)
    except (ConnectionResetError, asyncio.CancelledError):
        logging.info("SSE connection closed for job_id=%s", job_id)
    finally:
        try:
            await response.write_eof()
        except ConnectionResetError:
            pass

    return response


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Port number for this server"
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging level"
    )
    parser.add_argument(
        "--output-dir",
        default="downloads",
        help="Directory where tagged .m4a files are saved"
    )
    parser.add_argument(
        "--raw-cache-dir",
        default="raw-cache",
        help="Directory where downloaded, untagged source audio files are cached"
    )
    return parser.parse_args()


def main():
    global output_dir, raw_cache_dir

    args = parse_args()
    logging.getLogger().setLevel(getattr(logging, args.log_level))
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    logging.info("Saving processed tracks to %s", output_dir)

    raw_cache_dir = Path(args.raw_cache_dir).expanduser().resolve()
    raw_cache_dir.mkdir(parents=True, exist_ok=True)
    logging.info("Caching raw downloaded tracks in %s", raw_cache_dir)

    app = web.Application(middlewares=[cors_middleware])
    app["job_tasks"] = set()
    app["job_queue"] = asyncio.Queue()
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    app.router.add_post("/start", start_job)
    app.router.add_get("/progress/{job_id}", get_progress)
    app.router.add_get("/download/{job_id}", download_job)
    app.router.add_get("/progress-stream/{job_id}", stream_progress)
    app.router.add_static("/", path="./frontend", show_index=True)

    web.run_app(app, port=args.port)


if __name__ == "__main__":
    main()
