"""Tests for local BGM discovery, commands, and playback lifecycle."""

import asyncio
from pathlib import Path
import wave

import pytest

from chaihuo_reachy.bgm import (
    BgmTrack,
    clean_track_title,
    list_bgm_tracks,
    parse_bgm_command,
    resolve_bgm_track,
)
from chaihuo_reachy.config import Config
from chaihuo_reachy.engine import ConversationEngine


def test_list_and_resolve_bgm_tracks(tmp_path: Path) -> None:
    (tmp_path / "周杰伦 - 青花瓷.wav").write_bytes(b"RIFF")
    (tmp_path / "ignore.mp3").write_bytes(b"ID3")

    tracks = list_bgm_tracks(tmp_path)

    assert [track.title for track in tracks] == ["周杰伦 - 青花瓷"]
    assert resolve_bgm_track(tracks[0].id, tmp_path) == tracks[0]
    assert resolve_bgm_track("../outside.wav", tmp_path) is None


def test_clean_encrypted_source_suffixes() -> None:
    path = Path("周杰伦 - 青花瓷 [mqms2].mgg2.flac")
    assert clean_track_title(path) == "周杰伦 - 青花瓷"


def test_parse_bgm_commands() -> None:
    tracks = [BgmTrack("青花瓷.wav", "周杰伦 - 青花瓷", Path("青花瓷.wav"))]

    assert parse_bgm_command("播放音乐", tracks) == ("play", None)
    assert parse_bgm_command("播放音乐关", tracks) == ("play", None)
    assert parse_bgm_command("播放音乐青花瓷", tracks) == ("play", tracks[0])
    assert parse_bgm_command("把音乐关掉", tracks) == ("stop", None)
    assert parse_bgm_command("今天天气如何", tracks) is None


@pytest.mark.asyncio
async def test_engine_bgm_start_and_stop(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "测试音乐.wav"
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24_000)
        wav.writeframes(b"\0\0" * 24_000)
    track = BgmTrack(path.name, "测试音乐", path)

    class Audio:
        backend_name = "fake"
        volume = 1.0
        is_playing = False

        def set_output_sample_rate(self, _sample_rate: int) -> None:
            return None

        async def play(self, _pcm: bytes) -> None:
            self.is_playing = True

        def mark_playback_done(self) -> None:
            return None

        def stop_playback(self) -> None:
            self.is_playing = False

    class Motion:
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.reset_count = 0

        async def music_gesture(self) -> None:
            self.started.set()
            await asyncio.Event().wait()

        async def reset_ready_pose(self, duration: float = 0.8) -> None:
            self.reset_count += 1

    monkeypatch.setattr("chaihuo_reachy.engine.resolve_bgm_track", lambda _id: track)
    motion = Motion()
    engine = ConversationEngine(
        Config(), audio_backend=Audio(), motion=motion  # type: ignore[arg-type]
    )

    assert await engine.start_bgm(track.id) == "正在播放《测试音乐》。"
    assert engine._bgm_active is True
    await asyncio.wait_for(motion.started.wait(), timeout=0.2)
    assert await engine.stop_bgm() == "音乐已停止。"
    assert engine._bgm_active is False
    assert engine._external_interaction_active is False
    assert motion.reset_count == 1
