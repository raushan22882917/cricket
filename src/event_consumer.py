"""Event Consumer and Ingestion Server for Live Cricket Feeds.

Listens for ball-by-ball JSON events via HTTP webhook and also provides
a replay simulator for testing with mock feeds.
"""
import asyncio
import json
import logging
from typing import Callable, Awaitable, Optional
from aiohttp import web

from src.match_state import BallEvent, MatchState
import config

logger = logging.getLogger("EventConsumer")

class EventConsumer:
    def __init__(
        self,
        match_state: MatchState,
        on_event_callback: Callable[[BallEvent], Awaitable[None]],
        host: str = config.EVENT_SERVER_HOST,
        port: int = config.EVENT_SERVER_PORT
    ):
        self.match_state = match_state
        self.on_event = on_event_callback
        self.host = host
        self.port = port
        self.app = web.Application()
        self.runner: Optional[web.AppRunner] = None
        self.app.router.add_post("/event", self._handle_event_post)
        self.app.router.add_get("/health", self._handle_health)

    async def _handle_health(self, request: web.Request) -> web.Response:
        return web.json_response({
            "status": "healthy",
            "latest_event": self.match_state.latest_event.match_title if self.match_state.latest_event else None
        })

    async def _handle_event_post(self, request: web.Request) -> web.Response:
        try:
            payload = await request.json()
            event = BallEvent.from_dict(payload)
            # Dispatch to broadcast pipeline
            asyncio.create_task(self.on_event(event))
            return web.json_response({"status": "accepted", "over": event.over, "ball": event.ball})
        except Exception as e:
            logger.error(f"Error parsing event POST: {e}")
            return web.json_response({"error": str(e)}, status=400)

    async def start_http_server(self):
        """Starts HTTP server in the background for live webhook ingestion."""
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        for attempt in range(5):
            curr_port = self.port + attempt
            try:
                site = web.TCPSite(self.runner, self.host, curr_port)
                await site.start()
                self.port = curr_port
                logger.info(f"Event Ingestion Server listening on http://{self.host}:{self.port}/event")
                return
            except OSError as e:
                logger.warning(f"Port {curr_port} in use, trying next port...")
        logger.error(f"Could not bind Event Ingestion Server on {self.host}:{self.port}")

    async def stop_http_server(self):
        if self.runner:
            await self.runner.cleanup()

    async def run_mock_replay(self, mock_file_path: str = str(config.MOCK_FEED_FILE), ball_delay_seconds: float = 7.0):
        """Simulates live ball-by-ball stream from mock_match.json."""
        logger.info(f"Starting mock match replay from {mock_file_path} with {ball_delay_seconds}s interval...")
        try:
            with open(mock_file_path, "r", encoding="utf-8") as f:
                events = json.load(f)
        except Exception as e:
            logger.error(f"Could not load mock match file: {e}")
            return

        for i, ev_data in enumerate(events):
            event = BallEvent.from_dict(ev_data)
            logger.info(f"==> Ingesting Ball {event.over}.{event.ball} ({event.striker} facing {event.bowler})...")
            await self.on_event(event)
            if i < len(events) - 1:
                await asyncio.sleep(ball_delay_seconds)
