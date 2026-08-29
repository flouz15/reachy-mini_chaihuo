from __future__ import annotations

import wave

import pytest

from chaihuo_reachy.opening import load_opening_audio


def test_load_opening_audio_reads_mono_pcm(tmp_path) -> None:
    path = tmp_path / "opening.wav"
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(b"\x01\x00" * 2400)

    audio = load_opening_audio(path)

    assert audio.sample_rate == 24000
    assert audio.duration_s == pytest.approx(0.1)
    assert audio.pcm == b"\x01\x00" * 2400


def test_load_opening_audio_rejects_stereo(tmp_path) -> None:
    path = tmp_path / "opening.wav"
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x00\x00" * 20)

    with pytest.raises(ValueError, match="16-bit mono"):
        load_opening_audio(path)
