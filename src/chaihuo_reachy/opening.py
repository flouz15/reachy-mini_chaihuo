"""Offline opening-show assets and WAV loading helpers."""

from __future__ import annotations

import wave
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OPENING_AUDIO_PATH = PROJECT_ROOT / "assets/opening/chaihuo_opening_zh.wav"
DEFAULT_OPENING_TEXT_PATH = PROJECT_ROOT / "assets/opening/chaihuo_opening_zh.txt"


@dataclass(frozen=True)
class OpeningAudio:
    pcm: bytes
    sample_rate: int
    duration_s: float


def load_opening_audio(path: str | Path = DEFAULT_OPENING_AUDIO_PATH) -> OpeningAudio:
    audio_path = Path(path)
    if not audio_path.is_file():
        raise FileNotFoundError(f"开场音频不存在: {audio_path}")

    with wave.open(str(audio_path), "rb") as wav:
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        sample_rate = wav.getframerate()
        frame_count = wav.getnframes()
        if channels != 1 or sample_width != 2:
            raise ValueError("开场音频必须是 16-bit mono WAV")
        pcm = wav.readframes(frame_count)

    return OpeningAudio(
        pcm=pcm,
        sample_rate=sample_rate,
        duration_s=frame_count / sample_rate,
    )
