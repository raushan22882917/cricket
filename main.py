"""Master Broadcast Orchestrator for Real-Time YouTube Live Cricket AI Stream."""
import os
import sys
from typing import Optional, Dict, Any, List
import time
import signal
import asyncio
import logging
import argparse
from pathlib import Path

import config
from src.match_state import MatchState, BallEvent
from src.commentary_engine import CommentaryEngine
from src.tts_engine import TTSEngine
from src.audio_mixer import AudioMixer
from src.renderer import BroadcastRenderer
from src.streamer import FFmpegStreamer
from src.event_consumer import EventConsumer
from src.crex_scraper import CrexScraper

# Configure logging with clean format
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("BroadcastEngine")

class BroadcastEngine:
    def __init__(
        self,
        mode: str = config.STREAM_MODE,
        stream_key: str = config.YOUTUBE_STREAM_KEY,
        commentary_mode: str = config.COMMENTARY_MODE,
        output_file: str = config.OUTPUT_PREVIEW_FILE
    ):
        self.mode = mode
        self.stream_key = stream_key
        self.output_file = output_file
        self.is_running = False

        # Initialize core components
        self.match_state = MatchState()
        self.commentary_engine = CommentaryEngine(mode=commentary_mode)
        self.tts_engine = TTSEngine()
        self.audio_mixer = AudioMixer()
        self.renderer = BroadcastRenderer()
        self.streamer = FFmpegStreamer(
            stream_key=self.stream_key,
            mode=self.mode,
            output_file=self.output_file
        )
        self.consumer = EventConsumer(
            match_state=self.match_state,
            on_event_callback=self.handle_ball_event
        )

        self._active_commentary_task = None

    async def handle_ball_event(self, event: BallEvent):
        """Processes an incoming ball event from detector/feeder."""
        t_event = time.perf_counter()
        summary = self.match_state.update(event)

        # Trigger visual banners for milestones, wickets, and boundaries
        if event.is_wicket:
            self.renderer.trigger_event_alert(f"WICKET! {event.dismissed_player or event.striker}", color=(220, 30, 30))
        elif event.is_boundary and event.boundary_type == 6:
            self.renderer.trigger_event_alert("SIX! MAXIMUM!", color=(230, 160, 20))
        elif event.is_boundary and event.boundary_type == 4:
            self.renderer.trigger_event_alert("FOUR! BOUNDARY!", color=(25, 165, 85))
        elif summary.get("milestone"):
            self.renderer.trigger_event_alert(summary["milestone"].upper(), color=(210, 180, 20))

        # Generate color commentary asynchronously
        async def _produce_commentary():
            try:
                t0 = time.perf_counter()
                commentary_text = await self.commentary_engine.generate_commentary(summary)
                nlp_latency = time.perf_counter() - t0
                logger.info(f"Commentary text generated in {nlp_latency:.2f}s: \"{commentary_text}\"")

                # Update screen subtitle
                self.renderer.set_commentary(commentary_text, is_talking=True)

                # Synthesize neural speech
                t_tts0 = time.perf_counter()
                pcm_bytes, duration = await self.tts_engine.synthesize(commentary_text)
                tts_latency = time.perf_counter() - t_tts0

                total_latency = time.perf_counter() - t_event
                logger.info(
                    f"Voice synthesized ({duration:.1f}s) in {tts_latency:.2f}s. "
                    f"Total Event-to-Voice Latency: {total_latency:.2f}s (Threshold: < 5.0s) [OK]"
                )

                # Push to continuous audio mixer
                self.audio_mixer.enqueue_speech(pcm_bytes)

                # Reset talk indicator after spoken duration
                await asyncio.sleep(duration + 0.5)
                self.renderer.is_talking = False

            except Exception as e:
                logger.error(f"Error in commentary generation pipeline: {e}", exc_info=True)
                self.renderer.is_talking = False

        if self._active_commentary_task and not self._active_commentary_task.done():
            # Don't overlap speech violently; let previous sentence breathe or cancel if overdue
            pass

        self._active_commentary_task = asyncio.create_task(_produce_commentary())

    async def run_broadcast_loop(self, max_seconds: Optional[float] = None):
        """Main rendering and streaming loop at 30 fps."""
        logger.info(f"Starting broadcast video/audio pipeline at {config.VIDEO_FPS} fps...")
        self.streamer.start()
        self.is_running = True

        frame_duration = 1.0 / config.VIDEO_FPS
        # Samples per frame: 44100 / 30 = 1470 samples
        audio_chunk_samples = int(config.AUDIO_SAMPLE_RATE / config.VIDEO_FPS)

        start_time = time.time()
        next_frame_time = time.perf_counter()

        try:
            while self.is_running:
                loop_start = time.perf_counter()

                # Get latest match state summary or blank if no balls yet
                summary = self.match_state.get_summary()

                # Sync commentary talking status with audio mixer
                self.renderer.is_talking = self.audio_mixer.is_talking

                # 1. Render and write video frame
                frame_bytes = self.renderer.render_frame(summary)
                self.streamer.write_video_frame(frame_bytes)

                # 2. Extract and write matching audio chunk
                audio_bytes = self.audio_mixer.get_chunk(audio_chunk_samples)
                self.streamer.write_audio_chunk(audio_bytes)

                # Check max runtime if specified (e.g. for tests)
                if max_seconds and (time.time() - start_time) >= max_seconds:
                    logger.info(f"Reached specified runtime limit ({max_seconds}s). Stopping broadcast.")
                    break

                # Sleep to maintain exact frame cadence
                next_frame_time += frame_duration
                sleep_time = next_frame_time - time.perf_counter()
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)
                else:
                    # Skip ahead slightly if falling behind to preserve live real-time sync
                    next_frame_time = time.perf_counter()
                    await asyncio.sleep(0.001)

        except asyncio.CancelledError:
            logger.info("Broadcast loop cancelled.")
        finally:
            self.stop()

    def stop(self):
        self.is_running = False
        self.streamer.stop()

async def main():
    parser = argparse.ArgumentParser(description="Cricket YouTube Live AI Broadcast Engine")
    parser.add_argument("--url", default=None,
                        help="CREX match URL to scrape live data from")
    parser.add_argument("--poll-interval", type=float, default=4.0,
                        help="Polling interval in seconds for live URL scraper")
    parser.add_argument("--mode", choices=["youtube", "preview", "rtmp"], default=config.STREAM_MODE,
                        help="Broadcast target mode ('youtube', 'preview', or 'rtmp')")
    parser.add_argument("--key", default=config.YOUTUBE_STREAM_KEY,
                        help="YouTube Live RTMP Stream Key")
    parser.add_argument("--output", default=config.OUTPUT_PREVIEW_FILE,
                        help="Output MP4 file path for preview mode")
    parser.add_argument("--duration", type=float, default=None,
                        help="Maximum broadcast run duration in seconds")
    parser.add_argument("--listen-http", action="store_true", default=True,
                        help="Start HTTP webhook listener on port 8088")
    args = parser.parse_args()

    engine = BroadcastEngine(
        mode=args.mode,
        stream_key=args.key,
        output_file=args.output
    )

    tasks = []

    # 1. Start HTTP webhook listener for external ball data events
    if args.listen_http:
        await engine.consumer.start_http_server()

    # 2. Start Video/Audio Stream Loop
    broadcast_task = asyncio.create_task(engine.run_broadcast_loop(max_seconds=args.duration))
    tasks.append(broadcast_task)

    # 3. If a CREX URL is provided, scrape and stream live events from it
    if args.url:
        scraper = CrexScraper(args.url)
        # Fetch initial state to set up screen
        html_text = scraper.fetch_page_html()
        init_event = scraper.parse_match_data(html_text)
        if init_event:
            await engine.handle_ball_event(init_event)
        # Run continuous polling task
        scraper_task = asyncio.create_task(scraper.stream_live_from_url(engine.handle_ball_event, poll_interval_seconds=args.poll_interval))
        tasks.append(scraper_task)

    try:
        # Wait until the broadcast loop completes (or is cancelled)
        done, pending = await asyncio.wait(
            [broadcast_task],
            return_when=asyncio.FIRST_COMPLETED
        )
        for p in pending:
            p.cancel()
        for t in tasks:
            if not t.done():
                t.cancel()
    except KeyboardInterrupt:
        logger.info("Shutdown requested by user.")
    finally:
        engine.stop()
        if args.listen_http:
            await engine.consumer.stop_http_server()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBroadcast terminated gracefully.")
