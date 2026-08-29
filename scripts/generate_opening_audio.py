#!/usr/bin/env python3
"""Generate the event opening WAV once; runtime playback is fully offline."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace
import wave
from pathlib import Path

import numpy as np

from chaihuo_reachy.bailian.tts_client import BailianTTSClient
from chaihuo_reachy.config import load_config
from chaihuo_reachy.opening import (
    DEFAULT_OPENING_AUDIO_PATH,
    DEFAULT_OPENING_TEXT_PATH,
)

DIALECT_MARKER = "\n\n[天津话]\n"
DIALECT_MODEL = "qwen3-tts-flash"
DIALECT_VOICE = "Peter"


async def synthesize_segment(text: str, config) -> tuple[np.ndarray, int]:
    chunks: list[bytes] = []
    sample_rates: set[int] = set()

    def on_audio(pcm: bytes, sample_rate: int) -> None:
        chunks.append(bytes(pcm))
        sample_rates.add(int(sample_rate))

    client = BailianTTSClient(config, on_audio=on_audio)
    await client.open()
    try:
        await client.synthesize(text)
    finally:
        await client.close()

    if not chunks or len(sample_rates) != 1:
        raise RuntimeError("TTS 未返回有效的单采样率 PCM")

    return np.frombuffer(b"".join(chunks), dtype=np.int16).astype(np.float32), sample_rates.pop()


def resample(samples: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    if source_rate == target_rate or samples.size == 0:
        return samples
    target_size = max(1, round(samples.size * target_rate / source_rate))
    source_positions = np.linspace(0.0, 1.0, samples.size, endpoint=False)
    target_positions = np.linspace(0.0, 1.0, target_size, endpoint=False)
    return np.interp(target_positions, source_positions, samples).astype(np.float32)


async def generate(text_path: Path, output_path: Path) -> None:
    text = text_path.read_text(encoding="utf-8").strip()
    config = load_config()
    config.tts_volume = 100
    config.tts_speech_rate = 0.96

    if DIALECT_MARKER in text:
        main_text, dialect_text = text.split(DIALECT_MARKER, 1)
    else:
        main_text, dialect_text = text, ""

    main_samples, sample_rate = await synthesize_segment(main_text.strip(), config)
    segments = [main_samples]
    if dialect_text.strip():
        dialect_config = replace(
            config,
            bailian_tts_model=DIALECT_MODEL,
            bailian_tts_voice=DIALECT_VOICE,
        )
        dialect_samples, dialect_rate = await synthesize_segment(
            dialect_text.strip(), dialect_config
        )
        silence = np.zeros(round(sample_rate * 0.35), dtype=np.float32)
        segments.extend(
            [silence, resample(dialect_samples, dialect_rate, sample_rate)]
        )

    samples = np.concatenate(segments)
    peak = float(np.max(np.abs(samples))) if samples.size else 0.0
    if peak <= 0:
        raise RuntimeError("TTS 返回了静音音频")
    samples *= min(4.0, (32767.0 * 0.92) / peak)
    pcm = np.clip(samples, -32768, 32767).astype(np.int16).tobytes()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output_path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)

    print(f"saved={output_path} sample_rate={sample_rate} duration={len(pcm) / 2 / sample_rate:.2f}s")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--text", type=Path, default=DEFAULT_OPENING_TEXT_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OPENING_AUDIO_PATH)
    args = parser.parse_args()
    asyncio.run(generate(args.text, args.output))


if __name__ == "__main__":
    main()
