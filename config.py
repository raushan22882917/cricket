"""Configuration settings for Cricket YouTube Live AI Broadcast Engine."""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env if present
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

# YouTube RTMP Configuration
YOUTUBE_RTMP_BASE = os.getenv("YOUTUBE_RTMP_BASE", "rtmp://a.rtmp.youtube.com/live2")
YOUTUBE_STREAM_KEY = os.getenv("YOUTUBE_STREAM_KEY", "").strip()

# Broadcast Mode: 'youtube' (if stream key present), 'preview' (saves to MP4), or 'rtmp'
DEFAULT_MODE = "youtube" if YOUTUBE_STREAM_KEY else "preview"
STREAM_MODE = os.getenv("STREAM_MODE", DEFAULT_MODE).lower()

OUTPUT_PREVIEW_FILE = os.getenv("OUTPUT_PREVIEW_FILE", str(BASE_DIR / "broadcast_output.mp4"))

# Video Settings
VIDEO_WIDTH = int(os.getenv("VIDEO_WIDTH", "1280"))
VIDEO_HEIGHT = int(os.getenv("VIDEO_HEIGHT", "720"))
VIDEO_FPS = int(os.getenv("VIDEO_FPS", "30"))
VIDEO_BITRATE = os.getenv("VIDEO_BITRATE", "2500k")

# Audio Settings
AUDIO_SAMPLE_RATE = int(os.getenv("AUDIO_SAMPLE_RATE", "44100"))
AUDIO_CHANNELS = int(os.getenv("AUDIO_CHANNELS", "2"))
AUDIO_BITRATE = os.getenv("AUDIO_BITRATE", "128k")

# Commentary & NLP Settings
COMMENTARY_MODE = os.getenv("COMMENTARY_MODE", "auto") # 'gemini', 'offline', or 'auto'
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

# TTS Settings (Edge TTS voices: en-IN-PrabhatNeural, en-IN-NeerjaNeural, en-GB-RyanNeural, en-AU-WilliamNeural)
TTS_VOICE = os.getenv("TTS_VOICE", "en-IN-PrabhatNeural")
TTS_RATE = os.getenv("TTS_RATE", "+5%")
TTS_PITCH = os.getenv("TTS_PITCH", "+0Hz")

# Event Feeder Settings
EVENT_SERVER_HOST = os.getenv("EVENT_SERVER_HOST", "0.0.0.0")
EVENT_SERVER_PORT = int(os.getenv("EVENT_SERVER_PORT", "8088"))

# Path to data assets
DATA_DIR = BASE_DIR / "data"
PLAYERS_FILE = DATA_DIR / "players.json"
HERITAGE_FILE = DATA_DIR / "heritage.json"
