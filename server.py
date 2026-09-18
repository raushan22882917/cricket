"""Web Server & Real-Time Broadcast Hub for Cricket AI Broadcaster.

Provides modern Web UI, WebSocket live feed, in-browser audio streaming,
voice clip archival in /recordings, and Railway cloud deployment readiness.
"""
import os
import re
import sys
import time
import json
import asyncio
import logging
from pathlib import Path
from typing import Dict, Any, Set, Optional

from aiohttp import web
import aiohttp_cors

# Import existing core modules
from cricket_streamer import CrexParser, FreeTranslator, FastTTS, FastOverlayRenderer
from src.human_commentator import commentator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("WebServer")

BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "web"
RECORDINGS_DIR = BASE_DIR / "recordings"
RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)

class BroadcastHub:
    def __init__(self):
        self.active_websockets: Set[web.WebSocketResponse] = set()
        self.is_running = False
        self.broadcast_task: Optional[asyncio.Task] = None
        self.latest_match_state: Dict[str, Any] = {}
        self.latest_commentary = ""
        self.recordings_meta = []
        self._load_existing_recordings()

    def _load_existing_recordings(self):
        for p in sorted(RECORDINGS_DIR.glob("*.mp3"), key=os.path.getmtime, reverse=True)[:30]:
            self.recordings_meta.append({
                "filename": p.name,
                "url": f"/recordings/{p.name}",
                "title": p.name.replace(".mp3", "").replace("_", " ").title(),
                "time": time.strftime("%I:%M:%S %p", time.localtime(os.path.getmtime(p))),
                "duration": 5.0
            })

    async def broadcast_ws(self, msg_type: str, data: Any):
        """Pushes real-time JSON payload to all connected browser clients."""
        payload = json.dumps({"type": msg_type, "data": data})
        stale = []
        for ws in self.active_websockets:
            try:
                await ws.send_str(payload)
            except Exception:
                stale.append(ws)
        for ws in stale:
            self.active_websockets.discard(ws)

    async def start_broadcast(self, url: str, lang: str = "hi", stream_key: str = ""):
        if self.is_running:
            return {"ok": False, "error": "Broadcast is already running"}

        self.is_running = True
        self.broadcast_task = asyncio.create_task(self._run_broadcast_pipeline(url, lang, stream_key))
        await self.broadcast_ws("status", {"is_running": True})
        return {"ok": True}

    async def stop_broadcast(self):
        if not self.is_running:
            return {"ok": False, "error": "Broadcast is not running"}

        self.is_running = False
        if self.broadcast_task and not self.broadcast_task.done():
            self.broadcast_task.cancel()
            try:
                await self.broadcast_task
            except asyncio.CancelledError:
                pass
        self.broadcast_task = None
        await self.broadcast_ws("status", {"is_running": False})
        return {"ok": True}

    async def _run_broadcast_pipeline(self, url: str, lang: str, stream_key: str):
        logger.info(f"Starting broadcast pipeline for URL: {url} (Lang: {lang.upper()})")
        parser = CrexParser(url)
        translator = FreeTranslator() if lang == "hi" else None
        tts = FastTTS(language=lang)

        seen_balls = set()
        first_run = True

        try:
            logger.info("Entering live real-time CREX polling loop...")
            while self.is_running:
                try:
                    html_text = parser.fetch_html()
                    fresh_data = parser.parse(html_text)
                    self.latest_match_state = fresh_data

                    # Broadcast real-time match state to all browser clients
                    await self.broadcast_ws("match_state", fresh_data)

                    raw_balls = fresh_data.get("balls", [])
                    new_events = []

                    for b in reversed(raw_balls):
                        b_key = f"{b.get('over')}_{b.get('runs')}_{b.get('commentary')[:30]}"
                        if b_key not in seen_balls:
                            seen_balls.add(b_key)
                            new_events.append(b)

                    if first_run:
                        first_run = False
                        # On startup, broadcast the latest 2 balls
                        new_events = new_events[-2:] if len(new_events) >= 2 else new_events

                    for b in new_events:
                        if not self.is_running:
                            break

                        ball_over = b.get("over", "Live")
                        ball_runs = b.get("runs", "1")

                        # Humanize raw text into television-grade broadcast commentary
                        human_res = commentator.humanize(
                            b.get("spoken_line") or b.get("commentary", ""),
                            ball_info={**fresh_data, "runs": ball_runs, "over": ball_over},
                            lang=lang
                        )
                        spoken_text = human_res["spoken_text"]
                        badge = human_res["badge"]
                        rate = human_res["rate"]
                        pitch = human_res["pitch"]

                        self.latest_commentary = spoken_text

                        # Push feed item to timeline with human badge
                        await self.broadcast_ws("feed_item", {
                            "over": ball_over,
                            "runs": ball_runs,
                            "matchup": f"{human_res['bowler']} to {human_res['batter']}",
                            "badge": badge,
                            "commentary": spoken_text
                        })

                        # Synthesize neural voice with human emotional pacing
                        t0 = time.time()
                        pcm = await tts.speak(spoken_text, rate=rate, pitch=pitch)
                        duration = max(3.0, len(pcm) / (44100 * 4))

                        # Save MP3 audio file into /recordings/
                        filename = f"voice_{int(time.time())}_{ball_over.replace('.', '_')}.mp3"
                        file_path = RECORDINGS_DIR / filename

                        # Save MP3 from PCM via pydub
                        from pydub import AudioSegment
                        import io
                        seg = AudioSegment(
                            data=pcm,
                            sample_width=2,
                            frame_rate=44100,
                            channels=2
                        )
                        seg.export(str(file_path), format="mp3", bitrate="128k")

                        audio_url = f"/recordings/{filename}"
                        rec_item = {
                            "filename": filename,
                            "url": audio_url,
                            "title": f"[{badge}] Ball {ball_over} ({lang.upper()})",
                            "time": time.strftime("%I:%M:%S %p"),
                            "duration": duration
                        }
                        self.recordings_meta.insert(0, rec_item)

                        # Broadcast audio URL and speaking event to browser
                        await self.broadcast_ws("commentary", {
                            "text": spoken_text,
                            "badge": badge,
                            "audio_url": audio_url,
                            "duration": duration
                        })
                        await self.broadcast_ws("recording_ready", rec_item)

                        # Allow voice to finish playing
                        await asyncio.sleep(duration + 1.2)

                except Exception as e:
                    logger.warning(f"Error in live scrape poll: {e}")

                # Real-time poll interval (4 seconds)
                await asyncio.sleep(4)

        except asyncio.CancelledError:
            logger.info("Broadcast pipeline cancelled by user.")
        except Exception as e:
            logger.error(f"Broadcast pipeline error: {e}", exc_info=True)
        finally:
            self.is_running = False
            await self.broadcast_ws("status", {"is_running": False})


hub = BroadcastHub()

# Web Route Handlers
async def handle_index(request: web.Request) -> web.FileResponse:
    return web.FileResponse(WEB_DIR / "index.html")

async def handle_ws(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    hub.active_websockets.add(ws)

    # Send initial status
    await ws.send_str(json.dumps({
        "type": "status",
        "data": {"is_running": hub.is_running}
    }))
    if hub.latest_match_state:
        await ws.send_str(json.dumps({
            "type": "match_state",
            "data": hub.latest_match_state
        }))

    try:
        async for msg in ws:
            pass
    finally:
        hub.active_websockets.discard(ws)

    return ws

async def handle_api_status(request: web.Request) -> web.Response:
    return web.json_response({
        "is_running": hub.is_running,
        "match_state": hub.latest_match_state,
        "latest_commentary": hub.latest_commentary
    })

async def handle_api_recordings(request: web.Request) -> web.Response:
    return web.json_response(hub.recordings_meta[:50])

async def handle_api_start(request: web.Request) -> web.Response:
    try:
        body = await request.json()
        url = body.get("url", "").strip()
        lang = body.get("lang", "hi")
        stream_key = body.get("stream_key", "")

        if not url:
            return web.json_response({"ok": False, "error": "Match URL is required"}, status=400)

        res = await hub.start_broadcast(url=url, lang=lang, stream_key=stream_key)
        return web.json_response(res)
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)

async def handle_api_stop(request: web.Request) -> web.Response:
    res = await hub.stop_broadcast()
    return web.json_response(res)

def create_app() -> web.Application:
    app = web.Application()

    # Routes
    app.router.add_get("/", handle_index)
    app.router.add_get("/ws", handle_ws)
    app.router.add_get("/api/status", handle_api_status)
    app.router.add_get("/api/recordings", handle_api_recordings)
    app.router.add_post("/api/start", handle_api_start)
    app.router.add_post("/api/stop", handle_api_stop)

    # Static assets and recordings
    app.router.add_static("/static/", path=WEB_DIR, name="static")
    app.router.add_static("/recordings/", path=RECORDINGS_DIR, name="recordings")

    return app

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8088"))
    host = os.getenv("HOST", "0.0.0.0")
    app = create_app()
    logger.info(f"Cricket AI Web UI running on http://{host}:{port}")
    web.run_app(app, host=host, port=port)
