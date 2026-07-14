#!/usr/bin/env python3

import asyncio
import argparse
import json
import re
import uuid
import logging
from pathlib import Path

import aiohttp
from aiohttp import web
import mutagen.mp4


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

mp4_fn_pat = re.compile(r"/([^/]+)\.mp4")
catalogname_pat = re.compile(r"(.*)（(.*)）")

jobs = {}
output_dir = None


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

    def snapshot(self):
        return {
            "progress": self.progress,
            "total": self.total,
            "done": self.done,
            "error": self.error,
            "saved": self.saved,
            "status": self.status,
            "logs": self.logs[-200:],
        }

    def log(self, message):
        logging.info(message)
        self.logs.append(message)


def sanitize_filename(filename):
    sanitized = re.sub(r'[\\/:*?"<>|]+', "_", filename).strip()
    return sanitized or "track.m4a"


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

                headers = {"Cookie": cookie}
                state.log(f"Fetching URL: {url}")
                async with session.get(url, headers=headers) as resp:
                    state.log(f"Track response status={resp.status} for {filename}")
                    resp.raise_for_status()
                    data = await resp.read()
                    state.log(f"Fetched bytes={len(data)} for {filename}")

                output_path = unique_output_path(output_dir, filename)
                output_path.write_bytes(data)

                try:
                    state.log(f"Tagging {output_path.name}")

                    audio = mutagen.mp4.MP4(output_path)

                    track_title = track["workName"] + " - " + track["title"]
                    audio["\xa9nam"] = [track_title]
                    audio["\xa9ART"] = [track["artist"]]

                    album = track["album"]
                    match_album = catalogname_pat.match(album["cataloguename"])
                    album_title = match_album.group(1)
                    album_artist = match_album.group(2)

                    audio["\xa9alb"] = [album_title]
                    audio["aART"] = [album_artist]
                    audio["trkn"] = [(track_num, state.total)]
                    if album_art_cover:
                        audio["covr"] = [album_art_cover]

                    audio.save()

                    state.saved += 1
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
    return parser.parse_args()


def main():
    global output_dir

    args = parse_args()
    logging.getLogger().setLevel(getattr(logging, args.log_level))
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    logging.info("Saving processed tracks to %s", output_dir)

    app = web.Application(middlewares=[cors_middleware])
    app["job_tasks"] = set()
    app["job_queue"] = asyncio.Queue()
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    app.router.add_post("/start", start_job)
    app.router.add_get("/progress/{job_id}", get_progress)
    app.router.add_get("/progress-stream/{job_id}", stream_progress)
    app.router.add_static("/", path="./frontend", show_index=True)

    web.run_app(app, port=args.port)


if __name__ == "__main__":
    main()
