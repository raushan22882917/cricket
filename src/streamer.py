"""FFmpeg RTMP Pipeline Controller for YouTube Live and Local Preview Broadcasts."""
import os
import sys
import time
import signal
import tempfile
import subprocess
import logging
from pathlib import Path
from typing import Optional

import config

logger = logging.getLogger("Streamer")

class FFmpegStreamer:
    def __init__(
        self,
        stream_key: Optional[str] = None,
        mode: str = config.STREAM_MODE,
        output_file: str = config.OUTPUT_PREVIEW_FILE,
        width: int = config.VIDEO_WIDTH,
        height: int = config.VIDEO_HEIGHT,
        fps: int = config.VIDEO_FPS,
        sample_rate: int = config.AUDIO_SAMPLE_RATE,
        channels: int = config.AUDIO_CHANNELS
    ):
        self.stream_key = (stream_key or config.YOUTUBE_STREAM_KEY).strip()
        self.mode = mode.lower()
        self.output_file = output_file
        self.width = width
        self.height = height
        self.fps = fps
        self.sample_rate = sample_rate
        self.channels = channels

        self.process: Optional[subprocess.Popen] = None
        self.audio_pipe_path = os.path.join(tempfile.gettempdir(), f"cricket_audio_{os.getpid()}.pipe")
        self.audio_fd = None
        self.is_running = False

    def start(self):
        """Prepares pipes and launches FFmpeg subprocess."""
        # Ensure audio FIFO exists
        if os.path.exists(self.audio_pipe_path):
            os.unlink(self.audio_pipe_path)
        os.mkfifo(self.audio_pipe_path)

        # Build FFmpeg command
        cmd = [
            "ffmpeg",
            "-y",
            "-loglevel", "warning",
            # Video Input: Raw RGB24 from stdin
            "-f", "rawvideo",
            "-pix_fmt", "rgb24",
            "-s", f"{self.width}x{self.height}",
            "-r", str(self.fps),
            "-i", "pipe:0",
            # Audio Input: Raw PCM s16le from FIFO
            "-f", "s16le",
            "-ar", str(self.sample_rate),
            "-ac", str(self.channels),
            "-i", self.audio_pipe_path,
            # Video Encoding Settings
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-tune", "zerolatency",
            "-pix_fmt", "yuv420p",
            "-b:v", config.VIDEO_BITRATE,
            "-maxrate", config.VIDEO_BITRATE,
            "-bufsize", "5000k",
            "-g", str(self.fps * 2), # 2-second GOP for YouTube
            # Audio Encoding Settings
            "-c:a", "aac",
            "-b:a", config.AUDIO_BITRATE,
            "-ar", str(self.sample_rate),
        ]

        if self.mode == "youtube" and self.stream_key:
            target_url = f"{config.YOUTUBE_RTMP_BASE}/{self.stream_key}"
            cmd.extend(["-f", "flv", target_url])
            logger.info("Configured for DIRECT YOUTUBE LIVE RTMP streaming.")
        elif self.mode == "rtmp":
            target_url = f"{config.YOUTUBE_RTMP_BASE}/{self.stream_key}" if self.stream_key else "rtmp://127.0.0.1:1935/live/stream"
            cmd.extend(["-f", "flv", target_url])
            logger.info(f"Configured for RTMP stream to: {target_url}")
        else:
            # Preview file mode
            cmd.extend(["-f", "mp4", "-movflags", "+frag_keyframe+empty_moov", self.output_file])
            logger.info(f"Configured for LOCAL PREVIEW MODE: {self.output_file}")

        logger.info(f"Launching FFmpeg: {' '.join(cmd)}")
        self.process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            bufsize=10**7
        )

        # Open FIFO with O_RDWR so it never blocks regardless of FFmpeg's probe sequence
        self.audio_fd = os.open(self.audio_pipe_path, os.O_RDWR)
        self.is_running = True
        logger.info("FFmpeg process and audio pipe successfully connected.")

    def write_video_frame(self, frame_rgb_bytes: bytes):
        """Pushes raw RGB24 frame to FFmpeg stdin."""
        if not self.is_running or not self.process or not self.process.stdin:
            return
        try:
            self.process.stdin.write(frame_rgb_bytes)
        except (BrokenPipeError, OSError):
            logger.error("FFmpeg video pipe broken.")
            self.stop()

    def write_audio_chunk(self, audio_pcm_bytes: bytes):
        """Pushes raw PCM audio chunk to FFmpeg audio pipe."""
        if not self.is_running or self.audio_fd is None:
            return
        try:
            os.write(self.audio_fd, audio_pcm_bytes)
        except (BrokenPipeError, OSError):
            logger.error("FFmpeg audio pipe broken.")
            self.stop()

    def stop(self):
        """Gracefully shuts down FFmpeg and cleans up temporary pipes."""
        self.is_running = False
        if self.audio_fd is not None:
            try:
                os.close(self.audio_fd)
            except Exception:
                pass
            self.audio_fd = None

        if self.process:
            try:
                if self.process.stdin:
                    self.process.stdin.close()
                self.process.terminate()
                self.process.wait(timeout=3)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None

        if os.path.exists(self.audio_pipe_path):
            try:
                os.unlink(self.audio_pipe_path)
            except Exception:
                pass
        logger.info("FFmpeg streamer stopped.")
