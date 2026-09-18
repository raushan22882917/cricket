#!/usr/bin/env python3
"""
🏏 All-in-One Cricket AI Streaming Engine (URL -> Scrape -> AI Commentary -> Hindi/English TTS -> YouTube Live)

Usage:
  # 1. English commentary preview from CREX link:
  python cricket_streamer.py "https://crex.com/cricket-live-score/pak-w-vs-tha-w-2nd-qtr-final-womens-asian-games-t20-2026-match-updates-13Q0"

  # 2. Hindi commentary preview (free translator + Hindi neural voice):
  python cricket_streamer.py "https://crex.com/..." --lang hi

  # 3. Stream directly to YouTube Live:
  python cricket_streamer.py "https://crex.com/..." --lang hi --mode youtube --key "xxxx-xxxx-xxxx-xxxx"
"""
import os
import re
import sys
import html
import time
import json
import queue
import tempfile
import asyncio
import logging
import argparse
import threading
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import edge_tts
from bs4 import BeautifulSoup
from pydub import AudioSegment
from pydub.effects import normalize

sys.path.insert(0, str(Path(__file__).resolve().parent))
from src.human_commentator import commentator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("CricketStreamer")



class FreeTranslator:
    """100% Free Translation to Hindi with zero API keys."""
    def __init__(self):
        self._translator = None

    def _get_translator(self):
        if self._translator is None:
            try:
                from deep_translator import MyMemoryTranslator
                self._translator = MyMemoryTranslator(source="en-US", target="hi-IN")
            except Exception as e:
                logger.warning(f"Could not initialize MyMemoryTranslator: {e}")
        return self._translator

    def translate_to_hindi(self, text: str) -> str:
        # Check if already Devanagari/Hindi
        if re.search(r'[\u0900-\u097F]', text):
            return text

        clean = re.sub(r'<[^>]+>', '', text).strip()
        if not clean:
            return ""

        tr = self._get_translator()
        if tr:
            try:
                # Translate in concise chunks
                translated = tr.translate(clean[:300])
                if translated and len(translated) > 5:
                    return translated
            except Exception as e:
                logger.warning(f"Free translation notice: {e}, using original text.")

        return clean


class CrexParser:
    """Scrapes match details and commentary paragraphs line-by-line from CREX."""
    def __init__(self, url: str):
        self.url = url.strip()

    def fetch_html(self) -> str:
        try:
            cmd = [
                "curl", "-s",
                "-H", "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "-H", "Accept-Language: en-US,en;q=0.9",
                self.url
            ]
            return subprocess.check_output(cmd, timeout=12).decode("utf-8", errors="ignore")
        except Exception as e:
            logger.error(f"Error fetching URL: {e}")
            return ""

    def parse(self, html_text: str) -> Dict[str, Any]:
        soup = BeautifulSoup(html_text, "html.parser")

        # 1. Match Title & Venue
        title = soup.title.get_text() if soup.title else "Live Cricket Match"
        clean_title = title.split(",")[0].replace("🏆", "").strip()

        # Parse JSON state if present
        data_store = {}
        for s in html_text.split("<script"):
            if "stats.crickapi.com" in s:
                try:
                    body = s.split(">", 1)[1].split("</script>")[0].strip()
                    clean_json = html.unescape(body.replace("&q;", '"').replace("&a;", "&").replace("&s;", "'"))
                    data_store = json.loads(clean_json)
                    break
                except Exception:
                    pass

        venue = "International Stadium"
        for k, v in data_store.items():
            if "getMatchMetaData" in k and isinstance(v, list) and len(v) > 0:
                venue = v[0].get("v", venue)
                break

        # 2. Scorecard
        score_card = soup.find("div", class_=lambda x: x and "live-score-card" in x)
        total_runs = 92
        total_wickets = 7
        overs_str = "10.4"
        batting_team = "PAK-W"
        bowling_team = "THA-W"

        if score_card:
            sc_text = score_card.get_text(" ", strip=True)
            score_match = re.search(r'([A-Za-z\-]+)\s*(\d+)-(\d+)\s*\(([0-9\.]+)\)', sc_text)
            if score_match:
                batting_team = score_match.group(1).strip()
                total_runs = int(score_match.group(2))
                total_wickets = int(score_match.group(3))
                overs_str = score_match.group(4).strip()

        # 3. Batsmen and Bowler
        striker = "Umme Hani"
        striker_runs = 2
        striker_balls = 2
        non_striker = "Eman Naseer"
        non_striker_runs = 3
        non_striker_balls = 3
        bowler = "Thipatcha Puttawong"
        bowler_wickets = 0
        bowler_runs = 16
        bowler_overs = 1.4

        full_text = soup.get_text(" | ", strip=True)
        over_idx = full_text.find("OVER ")
        section = full_text[over_idx:over_idx + 250] if over_idx != -1 else full_text

        batter_matches = re.findall(r'([A-Za-z\s\-]+?)\s*\|\s*(\d+)\((\d+)\)', section)
        if len(batter_matches) >= 1:
            striker = batter_matches[0][0].strip()
            striker_runs = int(batter_matches[0][1])
            striker_balls = int(batter_matches[0][2])
        if len(batter_matches) >= 2:
            non_striker = batter_matches[1][0].strip()
            non_striker_runs = int(batter_matches[1][1])
            non_striker_balls = int(batter_matches[1][2])

        bowler_matches = re.findall(r'([A-Za-z\s\-]+?)\s*\|\s*(\d+)-(\d+)\(([0-9\.]+)\)', section)
        if bowler_matches:
            bowler = bowler_matches[0][0].strip()
            bowler_wickets = int(bowler_matches[0][1])
            bowler_runs = int(bowler_matches[0][2])
            bowler_overs = float(bowler_matches[0][3])

        # 4. Extract structured ball-by-ball commentary using exact CREX classes
        balls_data = []
        for over_span in soup.find_all("span", class_=lambda x: x and "cm-b-over" in x):
            parent = over_span.find_parent("div", class_=lambda x: x and "cm-b-roundcard" in x) or over_span.find_parent("div")
            c1_span = parent.find("span", class_=lambda x: x and "cm-b-comment-c1" in x) if parent else None
            ball_span = parent.find("span", class_=lambda x: x and "cm-b-ballupdate" in x) if parent else None
            c2_span = parent.find("span", class_=lambda x: x and "cm-b-comment-c2" in x) if parent else None

            over_str = over_span.get_text(strip=True)
            matchup_str = c1_span.get_text(strip=True) if c1_span else ""
            runs_str = ball_span.get_text(strip=True) if ball_span else "0"
            commentary_str = c2_span.get_text(" ", strip=True) if c2_span else ""
            commentary_clean = re.sub(r'\s+', ' ', commentary_str).strip()

            if commentary_clean:
                full_spoken_line = f"Over {over_str}: {matchup_str}. {commentary_clean}" if matchup_str else f"Over {over_str}. {commentary_clean}"
                balls_data.append({
                    "over": over_str,
                    "matchup": matchup_str,
                    "runs": runs_str,
                    "commentary": commentary_clean,
                    "spoken_line": full_spoken_line
                })

        cards = soup.find_all("div", class_=lambda x: x and "cm-b-roundcard" in x)
        paragraphs = []
        for b in reversed(balls_data):
            paragraphs.append(b["spoken_line"])

        for c in reversed(cards):
            txt = c.get_text(" ", strip=True)
            txt = re.sub(r'\s+', ' ', txt)
            txt = re.sub(r'^\d+:\d+\s*[AP]M\s*IST,\s*\d+:\d+\s*[AP]M\s*Local Time:\s*', '', txt)
            if txt and len(txt) > 20 and not any(txt[:25] in p for p in paragraphs):
                paragraphs.append(txt)

        if not paragraphs:
            paragraphs = [
                f"Live broadcast from {venue} between {batting_team} and {bowling_team}.",
                f"Score stands at {batting_team} {total_runs} for {total_wickets} in {overs_str} overs."
            ]

        return {
            "title": clean_title,
            "venue": venue,
            "batting_team": batting_team,
            "bowling_team": bowling_team,
            "total_runs": total_runs,
            "total_wickets": total_wickets,
            "overs": overs_str,
            "striker": striker,
            "striker_runs": striker_runs,
            "striker_balls": striker_balls,
            "non_striker": non_striker,
            "non_striker_runs": non_striker_runs,
            "non_striker_balls": non_striker_balls,
            "bowler": bowler,
            "bowler_figures": f"{bowler_wickets}-{bowler_runs} ({bowler_overs} ov)",
            "paragraphs": paragraphs
        }


class FastTTS:
    """Broadcaster neural voice generator with English & Hindi support."""
    def __init__(self, language: str = "en", voice: Optional[str] = None):
        self.language = language
        if voice:
            self.voice = voice
        elif language == "hi":
            # Native, energetic Hindi sports broadcaster
            self.voice = "hi-IN-MadhurNeural"
        else:
            # English broadcaster
            self.voice = "en-IN-PrabhatNeural"

    async def speak(self, text: str, rate: Optional[str] = None, pitch: Optional[str] = None) -> bytes:
        clean_text = re.sub(r'<[^>]+>', '', text).strip()
        words = clean_text.split()
        if len(words) > 40:
            clean_text = " ".join(words[:40]) + "..."

        target_rate = rate or ("+7%" if self.language == "hi" else "+6%")
        target_pitch = pitch or "+1Hz"

        comm = edge_tts.Communicate(clean_text, self.voice, rate=target_rate, pitch=target_pitch)
        buf = bytearray()
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                buf.extend(chunk["data"])

        if not buf:
            return b""

        import io
        seg = AudioSegment.from_file(io.BytesIO(buf), format="mp3")
        seg = seg.set_frame_rate(44100).set_channels(2).set_sample_width(2)
        # Studio presence boost & broadcast normalization
        seg = normalize(seg) + 1.5
        return seg.raw_data



class FastOverlayRenderer:
    """Renders 720p 30fps TV cricket broadcast graphics supporting Devanagari (Hindi) & English."""
    def __init__(self, width: int = 1280, height: int = 720):
        self.width = width
        self.height = height
        self.frame = 0
        self.font_large = self._load_font(26, bold=True)
        self.font_medium = self._load_font(18, bold=True)
        self.font_small = self._load_font(14, bold=False)

    def _load_font(self, size: int, bold: bool = False):
        # Prioritize Kohinoor for clean Devanagari & Latin rendering on macOS
        fonts = [
            "/System/Library/Fonts/Kohinoor.ttc",
            "/System/Library/Fonts/SFProText-Bold.otf" if bold else "/System/Library/Fonts/SFProText-Regular.otf",
            "/System/Library/Fonts/HelveticaNeue.ttc",
            "/Library/Fonts/Arial.ttf"
        ]
        for f in fonts:
            try: return ImageFont.truetype(f, size)
            except Exception: pass
        return ImageFont.load_default()

    def render(self, state: Dict[str, Any], subtitle: str, is_speaking: bool, alert_text: Optional[str] = None) -> bytes:
        self.frame += 1
        img = Image.new("RGB", (self.width, self.height), (15, 23, 42))
        draw = ImageDraw.Draw(img)

        # 1. Stadium Turf Background Gradient
        for y in range(0, self.height, 4):
            ratio = y / self.height
            draw.rectangle([0, y, self.width, y + 4], fill=(int(12 + ratio * 8), int(20 + ratio * 32), int(48 + ratio * 20)))

        # 2. Header Bar
        draw.rectangle([0, 0, self.width, 48], fill=(9, 14, 26))
        draw.line([0, 48, self.width, 48], fill=(35, 65, 115), width=2)
        # LIVE badge
        pulse = (np.sin(self.frame * 0.15) + 1.0) * 0.5
        draw.rounded_rectangle([25, 10, 95, 38], radius=6, fill=(int(200 + pulse * 55), 25, 25))
        draw.text((40, 15), "LIVE", fill=(255, 255, 255), font=self.font_medium)
        # Title
        draw.text((115, 15), f"{state['title'].upper()} • {state['venue']}", fill=(240, 240, 245), font=self.font_medium)

        # 3. Center Pitch Visualizer
        cx, cy = self.width // 2, 230
        draw.rounded_rectangle([cx - 150, cy - 100, cx + 150, cy + 100], radius=10, fill=(18, 28, 48), outline=(35, 60, 100), width=2)
        draw.rectangle([cx - 40, cy - 85, cx + 40, cy + 85], fill=(160, 140, 100))
        draw.line([cx - 40, cy - 55, cx + 40, cy - 55], fill=(255, 255, 255), width=2)
        draw.line([cx - 40, cy + 55, cx + 40, cy + 55], fill=(255, 255, 255), width=2)

        # Event Alert Banner (if any)
        if alert_text:
            draw.rectangle([0, 150, self.width, 215], fill=(210, 40, 40))
            draw.text((cx - 160, 162), alert_text, fill=(255, 255, 255), font=self.font_large)

        # 4. Commentary Bar
        c_y = self.height - 180
        draw.rectangle([0, c_y, self.width, c_y + 52], fill=(12, 18, 32))
        draw.line([0, c_y, self.width, c_y], fill=(30, 55, 95), width=1)
        # Mic badge
        if is_speaking:
            draw.rounded_rectangle([25, c_y + 10, 185, c_y + 42], radius=6, fill=(18, 130, 60))
            draw.text((35, c_y + 16), "🎙️ ON AIR (AI)", fill=(255, 255, 255), font=self.font_small)
        else:
            draw.rounded_rectangle([25, c_y + 10, 185, c_y + 42], radius=6, fill=(40, 55, 80))
            draw.text((35, c_y + 16), "🎙️ COLOR BOOTH", fill=(180, 200, 220), font=self.font_small)

        # Commentary Subtitle
        display_sub = subtitle[:95] + "..." if len(subtitle) > 95 else subtitle
        draw.text((205, c_y + 17), display_sub, fill=(245, 245, 250), font=self.font_medium)

        # 5. Lower Third Scorecard
        s_y = self.height - 120
        draw.rectangle([0, s_y, self.width, self.height], fill=(9, 14, 26))
        draw.line([0, s_y, self.width, s_y], fill=(40, 80, 150), width=3)

        # Left Score Pill
        draw.rectangle([0, s_y, 250, self.height], fill=(16, 38, 76))
        draw.text((25, s_y + 16), f"{state['batting_team']}", fill=(255, 215, 0), font=self.font_large)
        draw.text((120, s_y + 16), f"{state['total_runs']}/{state['total_wickets']}", fill=(255, 255, 255), font=self.font_large)
        draw.text((25, s_y + 60), f"OVERS: {state['overs']}", fill=(200, 220, 240), font=self.font_medium)

        # Middle Batsmen
        draw.text((280, s_y + 20), f"▶ {state['striker']}", fill=(255, 255, 255), font=self.font_medium)
        draw.text((490, s_y + 20), f"{state['striker_runs']} ({state['striker_balls']})", fill=(255, 215, 0), font=self.font_medium)
        draw.text((280, s_y + 55), f"   {state['non_striker']}", fill=(200, 210, 230), font=self.font_medium)
        draw.text((490, s_y + 55), f"{state['non_striker_runs']} ({state['non_striker_balls']})", fill=(200, 210, 230), font=self.font_medium)

        # Right Bowler
        bx = self.width - 340
        draw.line([bx - 15, s_y + 10, bx - 15, self.height - 10], fill=(30, 50, 80), width=1)
        draw.text((bx, s_y + 16), "BOWLING", fill=(140, 170, 210), font=self.font_small)
        draw.text((bx, s_y + 40), f"{state['bowler']}", fill=(255, 255, 255), font=self.font_medium)
        draw.text((bx, s_y + 68), f"{state['bowler_figures']}", fill=(255, 215, 0), font=self.font_medium)

        return img.tobytes()


class CricketStreamingEngine:
    """Master streaming orchestrator that reads link paragraphs, translates if needed, and streams live."""
    def __init__(
        self,
        url: str,
        mode: str = "preview",
        stream_key: str = "",
        language: str = "en",
        voice: Optional[str] = None,
        output_file: str = "broadcast_stream.mp4"
    ):
        self.parser = CrexParser(url)
        self.mode = mode
        self.stream_key = stream_key
        self.language = language
        self.output_file = output_file
        self.translator = FreeTranslator() if language == "hi" else None
        self.renderer = FastOverlayRenderer()
        self.tts = FastTTS(language=language, voice=voice)

        self.is_running = False
        self.current_subtitle = "Connecting to live match feed..."
        self.is_speaking = False
        self.active_alert = None

        self.audio_queue = queue.Queue()
        self.audio_pipe = os.path.join(tempfile.gettempdir(), f"cricket_live_audio_{os.getpid()}.pipe")

    def _generate_ambience_chunk(self, samples=1470) -> bytes:
        t = np.linspace(0, samples / 44100, samples, endpoint=False)
        hum = 0.08 * np.sin(2 * np.pi * 80 * t) + 0.05 * np.sin(2 * np.pi * 140 * t)
        noise = np.random.normal(0, 0.02, samples)
        mono = (hum + noise).astype(np.float32)
        stereo = np.column_stack((mono, mono))
        int16 = np.clip(stereo * 32767, -32768, 32767).astype(np.int16)
        return int16.tobytes()

    def _audio_writer_thread(self, audio_fd):
        active_voice = None
        voice_offset = 0

        while self.is_running:
            try:
                if active_voice is None:
                    if not self.audio_queue.empty():
                        active_voice = self.audio_queue.get_nowait()
                        voice_offset = 0
                        self.is_speaking = True

                if active_voice is not None:
                    chunk = active_voice[voice_offset:voice_offset + 5880]
                    voice_offset += len(chunk)
                    if len(chunk) < 5880:
                        chunk = chunk + self._generate_ambience_chunk(samples=(5880 - len(chunk)) // 4)
                        active_voice = None
                        self.is_speaking = False
                    os.write(audio_fd, chunk)
                else:
                    os.write(audio_fd, self._generate_ambience_chunk(samples=1470))

                time.sleep(1.0 / 33.0)
            except Exception:
                break

    async def run(self, max_paragraphs: Optional[int] = None):
        logger.info(f"Fetching match data from: {self.parser.url}")
        html_content = self.parser.fetch_html()
        match_data = self.parser.parse(html_content)
        logger.info(f"Match: {match_data['title']} | Score: {match_data['batting_team']} {match_data['total_runs']}/{match_data['total_wickets']}")
        logger.info(f"Loaded {len(match_data['paragraphs'])} commentary lines to broadcast in [{self.language.upper()}].")

        # Setup Audio FIFO
        if os.path.exists(self.audio_pipe):
            os.unlink(self.audio_pipe)
        os.mkfifo(self.audio_pipe)

        # Build FFmpeg command
        cmd = [
            "ffmpeg", "-y", "-loglevel", "warning",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "1280x720", "-r", "30", "-i", "pipe:0",
            "-f", "s16le", "-ar", "44100", "-ac", "2", "-i", self.audio_pipe,
            "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency", "-pix_fmt", "yuv420p",
            "-b:v", "2500k", "-maxrate", "2500k", "-bufsize", "5000k", "-g", "60",
            "-c:a", "aac", "-b:a", "128k", "-ar", "44100"
        ]

        if self.mode == "youtube" and self.stream_key:
            target = f"rtmp://a.rtmp.youtube.com/live2/{self.stream_key}"
            cmd.extend(["-f", "flv", target])
            logger.info(f"PITCHING DIRECTLY TO YOUTUBE LIVE RTMP (Language: {self.language.upper()})...")
        else:
            cmd.extend(["-f", "mp4", "-movflags", "+frag_keyframe+empty_moov", self.output_file])
            logger.info(f"RECORDING TO LOCAL PREVIEW: {self.output_file}")

        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        audio_fd = os.open(self.audio_pipe, os.O_RDWR)
        self.is_running = True

        # Start decoupled audio thread
        audio_thread = threading.Thread(target=self._audio_writer_thread, args=(audio_fd,), daemon=True)
        audio_thread.start()

        # Commentary worker task
        async def commentary_worker():
            para_list = match_data["paragraphs"]
            if max_paragraphs:
                para_list = para_list[:max_paragraphs]

            for idx, paragraph in enumerate(para_list):
                if not self.is_running:
                    break

                # Transform raw scraped text into human color commentary
                human_res = commentator.humanize(paragraph, ball_info=match_data, lang=self.language)
                spoken_text = human_res["spoken_text"]
                self.active_alert = human_res["badge"]
                self.current_subtitle = spoken_text

                logger.info(f"🎙️ [{human_res['badge']}] Line [{idx+1}/{len(para_list)}] [{self.language.upper()}]: {spoken_text}")

                # Generate humanized neural voice with dynamic emotional rate and pitch
                t0 = time.time()
                pcm = await self.tts.speak(spoken_text, rate=human_res["rate"], pitch=human_res["pitch"])
                duration = len(pcm) / (44100 * 4)
                logger.info(f"Broadcast voice ready ({duration:.1f}s, rate={human_res['rate']}) in {time.time()-t0:.2f}s")
                self.audio_queue.put(pcm)

                # Allow voice to finish speaking before next paragraph
                await asyncio.sleep(max(3.0, duration + 1.0))
                self.active_alert = None

            logger.info("All commentary paragraphs completed.")


        c_task = asyncio.create_task(commentary_worker())

        # Video rendering loop at 30 fps
        frame_interval = 1.0 / 30.0
        try:
            while self.is_running and not c_task.done():
                t_frame = time.perf_counter()
                frame_bytes = self.renderer.render(match_data, self.current_subtitle, self.is_speaking, self.active_alert)
                proc.stdin.write(frame_bytes)

                elapsed = time.perf_counter() - t_frame
                sleep_dur = frame_interval - elapsed
                if sleep_dur > 0:
                    await asyncio.sleep(sleep_dur)
                else:
                    await asyncio.sleep(0.001)

        finally:
            self.is_running = False
            try:
                proc.stdin.close()
                proc.wait(timeout=5)
            except Exception:
                pass
            try:
                os.close(audio_fd)
                os.unlink(self.audio_pipe)
            except Exception:
                pass
            logger.info(f"Stream complete! Output saved to: {self.output_file}")


def main():
    parser = argparse.ArgumentParser(description="Cricket AI Link-to-Broadcast Engine")
    parser.add_argument("url", nargs="?", default="https://crex.com/cricket-live-score/pak-w-vs-tha-w-2nd-qtr-final-womens-asian-games-t20-2026-match-updates-13Q0",
                        help="CREX match URL")
    parser.add_argument("--lang", choices=["en", "hi"], default="en",
                        help="Commentary language: 'en' (English) or 'hi' (Hindi)")
    parser.add_argument("--voice", default=None,
                        help="Override TTS voice model (e.g. 'hi-IN-MadhurNeural', 'en-IN-PrabhatNeural')")
    parser.add_argument("--mode", choices=["youtube", "preview"], default="preview",
                        help="Stream mode ('preview' saves MP4, 'youtube' pushes RTMP)")
    parser.add_argument("--key", default=os.getenv("YOUTUBE_STREAM_KEY", ""),
                        help="YouTube Live Stream Key")
    parser.add_argument("--output", default="live_crex_broadcast.mp4",
                        help="Output MP4 filename for preview")
    parser.add_argument("--lines", type=int, default=None,
                        help="Number of commentary lines to stream (default: all)")
    args = parser.parse_args()

    engine = CricketStreamingEngine(
        url=args.url,
        mode=args.mode,
        stream_key=args.key,
        language=args.lang,
        voice=args.voice,
        output_file=args.output
    )
    asyncio.run(engine.run(max_paragraphs=args.lines))

if __name__ == "__main__":
    main()
