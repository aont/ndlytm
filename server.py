#!/usr/bin/env python3

import asyncio
import json
import os
import re
import zipfile
import io
import uuid
import tempfile
import logging

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
        self.zip_data = None

    def log(self, message):
        logging.info(message)
        self.logs.append(message)


async def process_job(job_id, payload):
    state = jobs[job_id]

    cookie = payload["Cookie"]
    base_url = payload["BaseURL"]
    tracks = payload["PlayListsTracks"]

    state.total = len(tracks)
    state.log(f"Starting job with {state.total} tracks")

    zip_buffer = io.BytesIO()

    async with aiohttp.ClientSession() as session:
        with zipfile.ZipFile(zip_buffer, "w", compression=zipfile.ZIP_STORED) as zf:
            for i, track in enumerate(tracks):
                track_num = i + 1
                state.log(f"Downloading track {track_num}/{state.total}")

                m4a_path = track["m4a"]
                match = mp4_fn_pat.search(m4a_path)
                if not match:
                    state.log("Invalid m4a path")
                    continue

                filename = match.group(1) + ".m4a"
                url = base_url + m4a_path

                headers = {"Cookie": cookie}
                async with session.get(url, headers=headers) as resp:
                    data = await resp.read()

                temp = tempfile.NamedTemporaryFile(delete=False, suffix=".m4a")
                temp.write(data)
                temp.close()

                state.log(f"Tagging {filename}")

                audio = mutagen.mp4.MP4(temp.name)

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

                audio.save()

                zf.write(temp.name, arcname=filename)
                os.remove(temp.name)

                state.progress = track_num
                state.log(f"Finished {filename}")

    zip_buffer.seek(0)
    state.zip_data = zip_buffer.read()
    state.done = True
    state.log("Job completed successfully")


async def start_job(request):
    payload = await request.json()
    job_id = str(uuid.uuid4())

    jobs[job_id] = JobState()

    asyncio.create_task(process_job(job_id, payload))

    return web.json_response({"job_id": job_id})


async def get_progress(request):
    job_id = request.match_info["job_id"]
    state = jobs.get(job_id)

    if not state:
        return web.json_response({"error": "Invalid job ID"}, status=404)

    return web.json_response({
        "progress": state.progress,
        "total": state.total,
        "done": state.done,
        "logs": state.logs[-20:]
    })


async def download_zip(request):
    job_id = request.match_info["job_id"]
    state = jobs.get(job_id)

    if not state or not state.done:
        return web.Response(status=404)

    return web.Response(
        body=state.zip_data,
        headers={
            "Content-Disposition": "attachment; filename=tracks.zip",
            "Content-Type": "application/zip"
        }
    )


app = web.Application(middlewares=[cors_middleware])
app.router.add_post("/start", start_job)
app.router.add_get("/progress/{job_id}", get_progress)
app.router.add_get("/download/{job_id}", download_zip)
app.router.add_static("/", path="./frontend", show_index=True)

web.run_app(app, port=8080)
