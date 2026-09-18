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

import aiohttp
from aiohttp import web
import aiohttp_cors

# Import existing core modules
from cricket_streamer import CrexParser, FreeTranslator, FastTTS, FastOverlayRenderer, get_live_matches, resolve_match_url
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
        self.youtube_engine = None
        self.youtube_task: Optional[asyncio.Task] = None
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

        url = url.strip()
        if not url:
            return {"ok": False, "error": "Match link or search query is required."}

        # Smart Match Resolution: Accepts CREX (any tab/year), Cricbuzz, Cricinfo, or plain text
        resolved_url, resolve_note = resolve_match_url(url)
        target_url = resolved_url if resolved_url else url

        # Pre-flight check: verify URL can be accessed and is not a 404
        parser = CrexParser(target_url, lang=lang)
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
                    parser = CrexParser(target_url, lang=lang)
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
        self.broadcast_task = asyncio.create_task(self._run_broadcast_pipeline(target_url, lang, stream_key, parser=parser))

        # Launch YouTube Live RTMP stream if stream_key is provided
        if stream_key.strip():
            try:
                from cricket_streamer import CricketStreamingEngine
                self.youtube_engine = CricketStreamingEngine(
                    url=target_url,
                    mode="youtube",
                    stream_key=stream_key.strip(),
                    language=lang
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

    async def _run_broadcast_pipeline(self, url: str, lang: str, stream_key: str, parser: Optional[CrexParser] = None):
        logger.info(f"Starting ultra-fast real-time broadcast for URL: {url} (Lang: {lang.upper()})")
        if parser is None:
            parser = CrexParser(url, lang=lang)
        tts = FastTTS(language=lang)

        # Queue bounded to prevent backlog and maintain real-time pace
        ball_queue = asyncio.Queue(maxsize=10)
        seen_balls = set()
        first_run = True
        last_commentary_time = time.time()
        situation_index = 0

        async def voice_worker():
            """Synthesizes and broadcasts neural commentary audio without blocking real-time scraper."""
            nonlocal last_commentary_time
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

                    # Classify event for voice modulation; speaks the exact source commentary text
                    human_res = commentator.humanize(
                        b.get("spoken_line") or b.get("commentary", ""),
                        ball_info={**fresh_data, **b, "runs": ball_runs, "over": ball_over},
                        lang=lang
                    )
                    spoken_text = human_res["spoken_text"]
                    badge = human_res["badge"]
                    rate = human_res["rate"]
                    pitch = human_res["pitch"]

                    self.latest_commentary = spoken_text
                    last_commentary_time = time.time()

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

                    filename = f"voice_{int(time.time())}_{str(ball_over).replace('.', '_')}.mp3"
                    file_path = RECORDINGS_DIR / filename
                    with open(file_path, "wb") as f:
                        f.write(mp3_data)

                    # Estimate duration (~16000 bytes/sec at 128kbps)
                    duration = max(2.5, len(mp3_data) / 16000.0)

                    audio_url = f"/recordings/{filename}"
                    if is_studio_event:
                        rec_title = f"[{badge}] Studio - {ball_over} ({lang.upper()})"
                    else:
                        rec_title = f"[{badge}] Ball {ball_over} ({lang.upper()})"

                    rec_item = {
                        "filename": filename,
                        "url": audio_url,
                        "title": rec_title,
                        "time": time.strftime("%I:%M:%S %p"),
                        "duration": round(duration, 1)
                    }
                    self.recordings_meta.insert(0, rec_item)

                    # 3. Broadcast audio and speaking event to browser
                    await self.broadcast_ws("commentary", {
                        "text": spoken_text,
                        "badge": badge,
                        "audio_url": audio_url,
                        "duration": round(duration, 1)
                    })
                    await self.broadcast_ws("recording_ready", rec_item)

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
            logger.info("Entering ultra-fast live real-time CREX polling loop (1.5s interval)...")
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

                        if first_run:
                            first_run = False
                            # On start, queue the 2 most recent balls so speech starts immediately
                            if new_events:
                                new_events = new_events[-2:]

                        for b in new_events:
                            # Drop oldest if queue is full to enforce real-time pace
                            if ball_queue.full():
                                try:
                                    ball_queue.get_nowait()
                                except asyncio.QueueEmpty:
                                    pass
                            await ball_queue.put({"ball": b, "fresh_data": fresh_data})

                        # If no new ball event has arrived for > 14 seconds and queue is empty,
                        # provide situational studio color commentary (NEVER create fake duplicate ball deliveries)
                        now = time.time()
                        if not new_events and (now - last_commentary_time > 14.0) and ball_queue.empty():
                            is_upcoming = (fresh_data.get("total_runs", 0) == 0 and fresh_data.get("total_wickets", 0) == 0 and str(fresh_data.get("overs", "0.0")) == "0.0")
                            status_str = str(fresh_data.get("status", "")).lower()
                            is_completed = any(w in status_str for w in ["won by", "beat", "scores level", "drawn", "concluded", "tied", "match over"])
                            is_break = any(w in status_str for w in ["stumps", "innings break", "lunch", "tea", "rain", "delay", "bad light", "wet outfield", "break", "timeout"])

                            if is_upcoming:
                                sit_lines = [
                                    f"Live build-up from {fresh_data.get('venue', 'the ground')}: {fresh_data.get('batting_team')} vs {fresh_data.get('bowling_team')}. Both teams are conducting final warm-ups as we await the toss.",
                                    f"Conditions here at {fresh_data.get('venue', 'the venue')} look magnificent. The surface is well-prepared and promises great value for crisp cricket shots.",
                                    f"A key factor today will be how {fresh_data.get('batting_team')} negotiate the new ball against {fresh_data.get('bowling_team')}'s bowling attack in the opening powerplay.",
                                    f"Stay tuned right here on our broadcast. Toss, final playing elevens, and live commentary will begin shortly!"
                                ]
                                sit_over = "Pre-Match"
                                sit_matchup = f"{fresh_data.get('batting_team', '')} vs {fresh_data.get('bowling_team', '')}"
                            elif is_completed:
                                sit_lines = [
                                    f"Match wrap from {fresh_data.get('venue', 'the venue')}: {fresh_data.get('status', 'Match concluded')}!",
                                    f"Final scorecard recap: {fresh_data.get('batting_team')} finished with {fresh_data.get('total_runs', 0)} for {fresh_data.get('total_wickets', 0)} in {fresh_data.get('overs', '0.0')} overs. {fresh_data.get('team2_score', '')}.",
                                    f"A commanding performance here in {fresh_data.get('venue', 'the game')}. Both teams put on a memorable contest, but the key moments proved decisive.",
                                    f"Thank you for tuning into our AI broadcast coverage. Highlights and analysis continue here on the stream."
                                ]
                                sit_over = "Result"
                                sit_matchup = f"{fresh_data.get('batting_team', '')} vs {fresh_data.get('bowling_team', '')}"
                            elif is_break:
                                sit_lines = [
                                    f"Play update from {fresh_data.get('venue', 'the ground')}: It is currently {fresh_data.get('status', 'Stumps')}. {fresh_data.get('batting_team', 'Batting team')} stand at {fresh_data.get('total_runs', 0)} for {fresh_data.get('total_wickets', 0)} in {fresh_data.get('overs', '0.0')} overs.",
                                    f"At the crease for {fresh_data.get('batting_team', 'the team')}: {fresh_data.get('striker', 'The batter')} is batting on {fresh_data.get('striker_runs', 0)} off {fresh_data.get('striker_balls', 0)} deliveries, joined by {fresh_data.get('non_striker', 'partner')} on {fresh_data.get('non_striker_runs', 0)}.",
                                    f"For {fresh_data.get('bowling_team', 'the bowling side')}, {fresh_data.get('bowler', 'Bowler')} has bowled with figures of {fresh_data.get('bowler_figures', '0-0')} and an economy of {fresh_data.get('bowler_econ', '0.00')}.",
                                    f"Play will resume as scheduled. Keep listening to our live AI stream for continuous expert analysis and statistics."
                                ]
                                sit_over = "Stumps" if "stumps" in status_str else "Break"
                                sit_matchup = f"{fresh_data.get('batting_team', '')} vs {fresh_data.get('bowling_team', '')}"
                            else:
                                sit_lines = [
                                    f"Match update from {fresh_data.get('venue', 'the ground')}: {fresh_data.get('batting_team', 'Batting team')} are {fresh_data.get('total_runs', 0)} for {fresh_data.get('total_wickets', 0)} in {fresh_data.get('overs', '0.0')} overs. Current run rate is {fresh_data.get('crr', '0.00')}.",
                                    f"At the crease, {fresh_data.get('striker', 'The batter')} is playing on {fresh_data.get('striker_runs', 0)} off {fresh_data.get('striker_balls', 0)} deliveries, joined by {fresh_data.get('non_striker', 'partner')} on {fresh_data.get('non_striker_runs', 0)}.",
                                    f"{fresh_data.get('bowler', 'Bowler')} is currently bowling with figures of {fresh_data.get('bowler_figures', '0-0')} and an economy rate of {fresh_data.get('bowler_econ', '0.00')}.",
                                    f"The partnership between {fresh_data.get('striker', 'striker')} and {fresh_data.get('non_striker', 'non-striker')} is {fresh_data.get('partnership', 'holding firm')}."
                                ]
                                sit_over = "Update"
                                sit_matchup = f"{fresh_data.get('bowler', '')} to {fresh_data.get('striker', '')}"

                            sit_text = sit_lines[situation_index % len(sit_lines)]
                            situation_index += 1
                            last_commentary_time = now

                            sit_ball = {
                                "over": sit_over,
                                "runs": "",
                                "matchup": sit_matchup,
                                "commentary": sit_text,
                                "spoken_line": sit_text,
                                "is_studio": True
                            }
                            await ball_queue.put({"ball": sit_ball, "fresh_data": fresh_data})

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

                    # 1.5s poll rate for true real-time live streaming
                    await asyncio.sleep(1.5)

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
        lang = body.get("lang", "hi")
        stream_key = body.get("stream_key", "")

        if not url:
            return web.json_response({"ok": False, "error": "Match URL or team name is required"}, status=400)

        res = await hub.start_broadcast(url=url, lang=lang, stream_key=stream_key)
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
    app.router.add_get("/api/recordings", handle_api_recordings)
    app.router.add_get("/api/live-matches", handle_api_live_matches)
    app.router.add_post("/api/resolve", handle_api_resolve)
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
