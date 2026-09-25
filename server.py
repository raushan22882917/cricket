"""Web Server & Real-Time Broadcast Hub for Cricket AI Broadcaster.

Provides modern Web UI, WebSocket live feed, and in-browser audio streaming.
Voice audio is synthesized and streamed straight to the browser in memory —
never written to disk.
"""
import os
import json
import base64
import asyncio
import logging
from pathlib import Path
from typing import Dict, Any, Set, Optional

from dotenv import load_dotenv

load_dotenv()

import aiohttp
from aiohttp import web

# Import existing core modules
from cricket_streamer import CrexParser, create_tts, get_live_matches, resolve_match_url
from src.human_commentator import commentator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("WebServer")

BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "web"

class BroadcastHub:
    def __init__(self):
        self.active_websockets: Set[web.WebSocketResponse] = set()
        self.is_running = False
        self.broadcast_task: Optional[asyncio.Task] = None
        self.youtube_engine = None
        self.youtube_task: Optional[asyncio.Task] = None
        self.latest_match_state: Dict[str, Any] = {}
        self.latest_commentary = ""

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

    async def start_broadcast(self, url: str, lang: str = "hinglish", stream_key: str = "",
                               tts_provider: str = "edge", tts_api_key: str = "", tts_speaker: str = "",
                               gemini_api_key: str = ""):
        if self.is_running:
            return {"ok": False, "error": "Broadcast is already running"}

        url = url.strip()
        if not url:
            return {"ok": False, "error": "Match link or search query is required."}

        # Smart Match Resolution: Accepts CREX (any tab/year), Cricbuzz, Cricinfo, or plain text
        resolved_url, resolve_note = resolve_match_url(url)
        target_url = resolved_url if resolved_url else url

        # Pre-flight check: verify URL can be accessed and is not a 404
        parser = CrexParser(target_url, lang="hi" if lang in ("hi", "hinglish") else "en")
        try:
            html_text = await parser.fetch_html_async()
            if not html_text:
                return {"ok": False, "error": "Unable to fetch content from match URL."}
            init_data = parser.parse(html_text)
            self.latest_match_state = init_data
        except ValueError as ve:
            # If direct target fails or returned 404, attempt fuzzy match fallback using active fixtures
            fallback_url, fallback_note = resolve_match_url(url, force_fuzzy=True)
            if fallback_note and fallback_url != target_url:
                logger.info(f"Direct link returned 404 ({ve}), auto-resolved to live match: {fallback_url}")
                target_url = fallback_url
                resolve_note = fallback_note
                try:
                    parser = CrexParser(target_url, lang="hi" if lang in ("hi", "hinglish") else "en")
                    html_text = await parser.fetch_html_async()
                    init_data = parser.parse(html_text)
                    self.latest_match_state = init_data
                except Exception as fe:
                    return {"ok": False, "error": f"Match link failed: {fe}"}
            else:
                return {"ok": False, "error": str(ve)}
        except Exception as e:
            logger.warning(f"Pre-flight connection error: {e}")
            return {"ok": False, "error": f"Failed to connect to match URL: {e}"}

        self.is_running = True
        self.broadcast_task = asyncio.create_task(self._run_broadcast_pipeline(
            target_url, lang, stream_key, parser=parser,
            tts_provider=tts_provider, tts_api_key=tts_api_key, tts_speaker=tts_speaker,
            gemini_api_key=gemini_api_key
        ))

        # Launch YouTube Live RTMP stream if stream_key is provided
        if stream_key.strip():
            try:
                from cricket_streamer import CricketStreamingEngine
                self.youtube_engine = CricketStreamingEngine(
                    url=target_url,
                    mode="youtube",
                    stream_key=stream_key.strip(),
                    language=lang,
                    tts_provider=tts_provider,
                    tts_api_key=tts_api_key or None,
                    tts_speaker=tts_speaker or None,
                    gemini_api_key=gemini_api_key or None
                )
                self.youtube_task = asyncio.create_task(self.youtube_engine.run())
                logger.info(f"YouTube Live RTMP broadcast engine launched for stream key: {stream_key[:4]}****")
            except Exception as ye:
                logger.error(f"Failed to start YouTube streaming engine: {ye}")

        await self.broadcast_ws("status", {
            "is_running": True,
            "has_youtube": bool(stream_key.strip()),
            "target": "YouTube Live & Web" if stream_key.strip() else "Web Browser"
        })
        if resolve_note:
            await self.broadcast_ws("match_resolved", {
                "original": url,
                "resolved_url": target_url,
                "note": resolve_note
            })
        if self.latest_match_state:
            await self.broadcast_ws("match_state", self.latest_match_state)
        return {
            "ok": True,
            "resolved_url": target_url,
            "note": resolve_note,
            "youtube_streaming": bool(stream_key.strip())
        }

    async def stop_broadcast(self):
        if not self.is_running:
            return {"ok": False, "error": "Broadcast is not running"}

        self.is_running = False

        # Stop YouTube Live engine if active
        if self.youtube_engine:
            self.youtube_engine.is_running = False
        if self.youtube_task and not self.youtube_task.done():
            self.youtube_task.cancel()
            try:
                await self.youtube_task
            except asyncio.CancelledError:
                pass
        self.youtube_task = None
        self.youtube_engine = None

        # Stop Web broadcast pipeline
        if self.broadcast_task and not self.broadcast_task.done():
            self.broadcast_task.cancel()
            try:
                await self.broadcast_task
            except asyncio.CancelledError:
                pass
        self.broadcast_task = None
        await self.broadcast_ws("status", {"is_running": False})
        return {"ok": True}

    async def _run_broadcast_pipeline(self, url: str, lang: str, stream_key: str, parser: Optional[CrexParser] = None,
                                       tts_provider: str = "edge", tts_api_key: str = "", tts_speaker: str = "",
                                       gemini_api_key: str = ""):
        logger.info(f"Starting ultra-fast real-time broadcast for URL: {url} (Lang: {lang.upper()}, Voice: {tts_provider})")
        if parser is None:
            parser = CrexParser(url, lang="hi" if lang in ("hi", "hinglish") else "en")
        tts = create_tts(language=lang, provider=tts_provider, api_key=tts_api_key or None, speaker=tts_speaker or None)

        # Queue bounded to prevent backlog and maintain real-time pace
        ball_queue = asyncio.Queue(maxsize=10)
        seen_balls = set()

        async def voice_worker():
            """Synthesizes and broadcasts neural commentary audio without blocking real-time scraper."""
            while self.is_running:
                try:
                    event = await asyncio.wait_for(ball_queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                except asyncio.CancelledError:
                    break

                try:
                    b = event["ball"]
                    fresh_data = event["fresh_data"]
                    ball_over = b.get("over", "Live")
                    ball_runs = b.get("runs", "1")

                    # Generate dynamic Hinglish live commentary taking all ball text as input
                    human_res = await commentator.humanize_async(
                        b.get("spoken_line") or b.get("commentary", ""),
                        ball_info={**fresh_data, **b, "runs": ball_runs, "over": ball_over},
                        lang=lang,
                        gemini_api_key=gemini_api_key
                    )
                    spoken_text = human_res["spoken_text"]
                    badge = human_res["badge"]
                    rate = human_res["rate"]
                    pitch = human_res["pitch"]

                    self.latest_commentary = spoken_text

                    # 1. Instantly push timeline feed item ONLY for actual ball deliveries (never studio updates)
                    is_studio_event = (
                        b.get("is_studio")
                        or human_res.get("event") == "studio"
                        or str(ball_over).lower() in ["pre-match", "result", "summary", "preview", "post-match", "break", "stumps", "update", "live"]
                    )
                    if not is_studio_event:
                        await self.broadcast_ws("feed_item", {
                            "over": ball_over,
                            "runs": ball_runs,
                            "matchup": f"{human_res['bowler']} to {human_res['batter']}",
                            "badge": badge,
                            "commentary": spoken_text
                        })

                    # 2. Fast neural audio synthesis directly to MP3 bytes (sub-second)
                    mp3_data = await tts.speak_mp3(spoken_text, rate=rate, pitch=pitch)
                    if not mp3_data:
                        continue

                    # Estimate duration (~16000 bytes/sec at 128kbps)
                    duration = max(2.5, len(mp3_data) / 16000.0)

                    # Stream audio straight to the browser as a data URI — never touches disk.
                    audio_url = "data:audio/mpeg;base64," + base64.b64encode(mp3_data).decode("ascii")

                    # 3. Broadcast audio and speaking event to browser
                    await self.broadcast_ws("commentary", {
                        "text": spoken_text,
                        "badge": badge,
                        "audio_url": audio_url,
                        "duration": round(duration, 1)
                    })

                    # Sleep only for the voice duration (shorten if queue is waiting)
                    pending = ball_queue.qsize()
                    wait_time = max(1.5, duration - (0.6 if pending > 0 else 0.0))
                    await asyncio.sleep(wait_time)

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.warning(f"Voice worker exception: {e}")

        # Start decoupled voice worker task
        voice_task = asyncio.create_task(voice_worker())

        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9"
        }
        connector = aiohttp.TCPConnector(limit=10, keepalive_timeout=60)

        try:
            logger.info("Entering ultra-fast live real-time CREX polling loop (1.0s interval)...")
            async with aiohttp.ClientSession(connector=connector, headers=headers) as session:
                while self.is_running:
                    try:
                        # Ultra-fast non-blocking fetch (50-100ms)
                        html_text = await parser.fetch_html_async(session=session)
                        if not html_text:
                            await asyncio.sleep(1.0)
                            continue

                        fresh_data = parser.parse(html_text)
                        self.latest_match_state = fresh_data

                        # Instantly push fresh score and state to all browser clients (<50ms)
                        await self.broadcast_ws("match_state", fresh_data)

                        raw_balls = fresh_data.get("balls", [])
                        new_events = []

                        for b in reversed(raw_balls):
                            b_key = f"{b.get('over')}_{b.get('runs')}_{b.get('commentary')[:30]}"
                            if b_key not in seen_balls:
                                seen_balls.add(b_key)
                                new_events.append(b)

                        # Never speak a backlog of historical balls — whether it's the very
                        # first poll after start, or a later poll where the source suddenly
                        # returns several balls at once (a scrape gap, a slow first response,
                        # etc.), always catch up to just the latest delivery or two so
                        # commentary never floods/overlaps.
                        if len(new_events) > 2:
                            new_events = new_events[-2:]

                        for b in new_events:
                            # Drop oldest if queue is full to enforce real-time pace
                            if ball_queue.full():
                                try:
                                    ball_queue.get_nowait()
                                except asyncio.QueueEmpty:
                                    pass
                            await ball_queue.put({"ball": b, "fresh_data": fresh_data})

                        consecutive_errors = 0
                    except asyncio.CancelledError:
                        break
                    except ValueError as ve:
                        consecutive_errors += 1
                        logger.warning(f"Parse/Fetch error: {ve}")
                        if consecutive_errors >= 3:
                            await self.broadcast_ws("error", {"message": str(ve)})
                            break
                    except Exception as e:
                        consecutive_errors += 1
                        logger.warning(f"Error in fast scrape poll: {e}")
                        if consecutive_errors >= 5:
                            await self.broadcast_ws("error", {"message": f"Connection lost to match feed: {e}"})
                            break

                    # 1s poll rate for true real-time live streaming
                    await asyncio.sleep(1.0)

        except asyncio.CancelledError:
            logger.info("Broadcast pipeline cancelled by user.")
        except Exception as e:
            logger.error(f"Broadcast pipeline error: {e}", exc_info=True)
            await self.broadcast_ws("error", {"message": f"Pipeline error: {str(e)}"})
        finally:
            self.is_running = False
            if voice_task and not voice_task.done():
                voice_task.cancel()
                try:
                    await voice_task
                except asyncio.CancelledError:
                    pass
            await self.broadcast_ws("status", {"is_running": False})


hub = BroadcastHub()

# Web Route Handlers
async def handle_index(request: web.Request) -> web.FileResponse:
    return web.FileResponse(WEB_DIR / "index.html")

async def handle_ws(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse(heartbeat=30.0, autoping=True)
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

async def handle_api_live_matches(request: web.Request) -> web.Response:
    matches = await asyncio.to_thread(get_live_matches)
    return web.json_response({"ok": True, "matches": matches})

async def handle_api_resolve(request: web.Request) -> web.Response:
    try:
        body = await request.json()
        query = body.get("query", "").strip()
        if not query:
            return web.json_response({"ok": False, "error": "Query is required"}, status=400)
        resolved_url, note = resolve_match_url(query)
        return web.json_response({"ok": True, "resolved_url": resolved_url, "note": note})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)

async def handle_api_start(request: web.Request) -> web.Response:
    try:
        body = await request.json()
        url = body.get("url", "").strip()
        lang = body.get("lang", "hinglish")
        stream_key = body.get("stream_key", "")
        tts_provider = body.get("tts_provider", "edge").strip() or "edge"
        tts_api_key = body.get("sarvam_api_key", "").strip() or os.getenv("SARVAM_API_KEY", "").strip()
        tts_speaker = body.get("sarvam_speaker", "").strip()
        gemini_api_key = body.get("gemini_api_key", "").strip() or os.getenv("GEMINI_API_KEY", "").strip()

        if not url:
            return web.json_response({"ok": False, "error": "Match URL or team name is required"}, status=400)

        if tts_provider == "sarvam" and not tts_api_key:
            return web.json_response({"ok": False, "error": "Sarvam API key is required to use the Sarvam voice engine"}, status=400)

        res = await hub.start_broadcast(url=url, lang=lang, stream_key=stream_key,
                                         tts_provider=tts_provider, tts_api_key=tts_api_key, tts_speaker=tts_speaker,
                                         gemini_api_key=gemini_api_key)
        status_code = 200 if res.get("ok") else 400
        return web.json_response(res, status=status_code)
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)

async def handle_api_stop(request: web.Request) -> web.Response:
    res = await hub.stop_broadcast()
    return web.json_response(res)

async def handle_favicon(request: web.Request) -> web.Response:
    return web.Response(status=204)

def create_app() -> web.Application:
    app = web.Application()

    # Routes
    app.router.add_get("/", handle_index)
    app.router.add_get("/favicon.ico", handle_favicon)
    app.router.add_get("/ws", handle_ws)
    app.router.add_get("/api/status", handle_api_status)
    app.router.add_get("/api/live-matches", handle_api_live_matches)
    app.router.add_post("/api/resolve", handle_api_resolve)
    app.router.add_post("/api/start", handle_api_start)
    app.router.add_post("/api/stop", handle_api_stop)

    # Static assets
    app.router.add_static("/static/", path=WEB_DIR, name="static")

    return app

if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000" if os.getenv("RENDER") else "8088"))
    host = os.getenv("HOST", "0.0.0.0")
    app = create_app()
    logger.info(f"Cricket AI Web UI running on http://{host}:{port}")
    web.run_app(app, host=host, port=port)
