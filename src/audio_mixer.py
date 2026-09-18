"""Continuous audio mixer for stadium atmosphere and queued commentary voiceovers."""
import io
import math
import numpy as np
import logging
from typing import Optional, List
import asyncio

import config

logger = logging.getLogger("AudioMixer")

class AudioMixer:
    """
    Maintains a continuous 44.1kHz 16-bit stereo PCM stream.
    Plays subtle stadium ambience continuously and seamlessly layers
    commentary voiceover clips when available.
    """
    def __init__(
        self,
        sample_rate: int = config.AUDIO_SAMPLE_RATE,
        channels: int = config.AUDIO_CHANNELS,
        ambience_volume: float = 0.12, # gentle stadium hum
        voice_volume: float = 1.0
    ):
        self.sample_rate = sample_rate
        self.channels = channels
        self.ambience_volume = ambience_volume
        self.voice_volume = voice_volume

        self.voice_queue = asyncio.Queue()
        self.active_voice_samples: Optional[np.ndarray] = None
        self.voice_offset: int = 0
        self.is_talking: bool = False

        # Pre-synthesize an atmospheric stadium crowd murmur bed (low-passed murmur with subtle modulation)
        self._ambience_buffer = self._generate_stadium_ambience(seconds=10)
        self._ambience_index = 0

    def _generate_stadium_ambience(self, seconds: int = 10) -> np.ndarray:
        """Generates soft, atmospheric crowd murmur bed using filtered noise harmonics."""
        num_samples = self.sample_rate * seconds
        t = np.linspace(0, seconds, num_samples, endpoint=False)

        # Ambient low-frequency crowd hum (60Hz to 350Hz harmonics)
        hum = (
            0.4 * np.sin(2 * np.pi * 75 * t) +
            0.3 * np.sin(2 * np.pi * 120 * t + 0.5) +
            0.2 * np.sin(2 * np.pi * 210 * t + 1.2) +
            0.15 * np.sin(2 * np.pi * 320 * t + 2.0)
        )
        # Slow swell modulation (breathing crowd dynamics)
        swell = 0.8 + 0.2 * np.sin(2 * np.pi * 0.2 * t)
        
        # Soft band-passed noise simulation
        noise = np.random.normal(0, 0.08, num_samples)
        # Smooth noise using moving average
        kernel_size = 200
        kernel = np.ones(kernel_size) / kernel_size
        smooth_noise = np.convolve(noise, kernel, mode="same")

        ambience = (hum * 0.5 + smooth_noise * 1.5) * swell * self.ambience_volume
        # Stereo expansion (subtle phase shift for wide soundstage)
        stereo_left = ambience
        stereo_right = np.roll(ambience, int(self.sample_rate * 0.02)) # 20ms Haas effect

        stereo_ambience = np.column_stack((stereo_left, stereo_right)).astype(np.float32)
        return stereo_ambience

    def enqueue_speech(self, pcm_bytes: bytes):
        """Enqueues newly synthesized commentary PCM bytes (s16le)."""
        if not pcm_bytes:
            return
        # Convert raw s16le bytes to normalized float32 array
        samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        if self.channels == 2 and len(samples) % 2 == 0:
            samples = samples.reshape(-1, 2)
        elif self.channels == 2 and len(samples) % 2 != 0:
            samples = samples[:-1].reshape(-1, 2)
        else:
            samples = np.column_stack((samples, samples))

        self.voice_queue.put_nowait(samples)
        logger.info(f"Enqueued voice clip of {len(samples)/self.sample_rate:.2f}s into broadcast mixer.")

    def get_chunk(self, chunk_samples: int = 1024) -> bytes:
        """
        Extracts the next chunk of mixed audio (ambience + speech) in s16le PCM format.
        """
        # 1. Grab base ambience slice
        amb_end = self._ambience_index + chunk_samples
        if amb_end <= len(self._ambience_buffer):
            amb_slice = self._ambience_buffer[self._ambience_index:amb_end].copy()
            self._ambience_index = amb_end % len(self._ambience_buffer)
        else:
            first_part = self._ambience_buffer[self._ambience_index:]
            second_part = self._ambience_buffer[:(amb_end - len(self._ambience_buffer))]
            amb_slice = np.vstack((first_part, second_part)).copy()
            self._ambience_index = (amb_end - len(self._ambience_buffer)) % len(self._ambience_buffer)

        # 2. Layer active voice if currently playing or dequeuing
        mixed = amb_slice
        if self.active_voice_samples is None:
            if not self.voice_queue.empty():
                self.active_voice_samples = self.voice_queue.get_nowait()
                self.voice_offset = 0
                self.is_talking = True

        if self.active_voice_samples is not None:
            rem_voice = len(self.active_voice_samples) - self.voice_offset
            voice_take = min(chunk_samples, rem_voice)

            voice_slice = self.active_voice_samples[self.voice_offset : self.voice_offset + voice_take]
            # Duck ambience slightly when commentator is speaking (duck to 50%)
            mixed[:voice_take] = (amb_slice[:voice_take] * 0.5) + (voice_slice * self.voice_volume)
            self.voice_offset += voice_take

            if self.voice_offset >= len(self.active_voice_samples):
                self.active_voice_samples = None
                self.voice_offset = 0
                self.is_talking = False

        # 3. Clip and convert to int16 PCM bytes
        np.clip(mixed, -1.0, 1.0, out=mixed)
        int16_mixed = (mixed * 32767).astype(np.int16)
        return int16_mixed.tobytes()
