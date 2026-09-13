from __future__ import annotations

import asyncio
import json
from typing import Any
from types import SimpleNamespace

import pytest

from chaihuo_reachy.bailian.asr_client import ASRResult, BailianASRClient
from chaihuo_reachy.config import Config
from chaihuo_reachy.engine import ConversationEngine


class _FakeWebSocket:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def send(self, message: str) -> None:
        self.messages.append(json.loads(message))


@pytest.mark.asyncio
async def test_asr_configures_vad_once_before_audio_ingestion() -> None:
    client = BailianASRClient(Config())
    websocket = _FakeWebSocket()
    client._ws = websocket  # type: ignore[assignment]
    client._connected = True
    await client.configure()
    assert len(websocket.messages) == 1
    assert websocket.messages[0]["type"] == "session.update"
    turn_detection = websocket.messages[0]["session"]["turn_detection"]
    assert turn_detection["silence_duration_ms"] == 600
    assert turn_detection["threshold"] == 0.5


def test_runtime_status_exposes_asr_endpoint_policy() -> None:
    engine = ConversationEngine(Config())
    asr_status = engine.runtime_status()["asr"]
    assert asr_status["vad_silence_ms"] == 600
    assert asr_status["initial_silence_timeout_s"] == 20.0
    assert asr_status["speech_max_duration_s"] == 15.0
    assert asr_status["last_end_reason"] == ""
    assert asr_status["frontend_v2"] is True
    assert asr_status["connected"] is False
    assert asr_status["connect_count"] == 0
    assert asr_status["reconnects"] == 0
    assert asr_status["last_error"] == ""


class _FakeAudio:
    capture_rms = 0.0

    async def start_capture(self):
        while True:
            yield b"\0" * 320
            await asyncio.sleep(0.001)


class _FakeASR:
    def __init__(self, events: list[tuple[float, ASRResult]]) -> None:
        self.events = events
        self.finished = False
        self.connected = False
        self.connect_calls = 0
        self.close_calls = 0
        self.fail_connects = 0

    @property
    def is_connected(self) -> bool:
        return self.connected

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *_args) -> None:
        await self.close()

    async def connect(self) -> None:
        self.connect_calls += 1
        if self.fail_connects > 0:
            self.fail_connects -= 1
            self.connected = False
            raise ConnectionError("ASR handshake failed")
        self.connected = True

    async def close(self) -> None:
        self.close_calls += 1
        self.connected = False

    def reset_turn(self) -> None:
        return None

    async def configure(self) -> None:
        return None

    async def send_audio(self, _chunk: bytes) -> None:
        if not self.connected:
            raise ConnectionError("ASR connection closed")
        return None

    async def finish(self) -> None:
        if not self.connected:
            raise ConnectionError("ASR connection closed")
        self.finished = True

    async def results(self):
        for delay, result in self.events:
            if delay:
                await asyncio.sleep(delay)
            yield result
        await asyncio.Event().wait()


def _engine_with_fake_asr(monkeypatch, events, *, initial: float = 0.03, maximum: float = 0.06):
    import chaihuo_reachy.engine as engine_module

    asr = _FakeASR(events)
    monkeypatch.setattr(engine_module, "BailianASRClient", lambda _cfg: asr)
    engine = ConversationEngine(
        Config(
            asr_initial_silence_timeout_s=initial,
            asr_speech_max_duration_s=maximum,
        ),
        audio_backend=_FakeAudio(),  # type: ignore[arg-type]
    )
    return engine, asr


def _fake_capture() -> Any:
    """An endless capture iterator, as opened by _listen_for_speech."""
    return _FakeAudio().start_capture().__aiter__()


@pytest.mark.asyncio
async def test_partial_and_final_transcript_are_committed_without_session_update(monkeypatch) -> None:
    engine, asr = _engine_with_fake_asr(monkeypatch, [
        (0.0, ASRResult(text="", speech_started=True)),
        (0.0, ASRResult(text="请介绍一下基地车")),
        (0.0, ASRResult(text="请介绍一下基地车。", is_final=True)),
    ])
    transcripts: list[tuple[str, bool]] = []
    engine.on_transcript(lambda text, final: transcripts.append((text, final)))

    assert await engine._listen_cloud_asr(capture=_fake_capture()) == "请介绍一下基地车。"
    assert transcripts[-1] == ("请介绍一下基地车。", True)
    assert engine._last_asr_end_reason == "completed"


@pytest.mark.asyncio
async def test_initial_silence_timeout_is_distinct_from_speech_timeout(monkeypatch) -> None:
    engine, asr = _engine_with_fake_asr(monkeypatch, [], initial=0.01, maximum=0.06)
    statuses: list[str] = []
    engine.on_asr_status(statuses.append)

    assert await engine._listen_cloud_asr(capture=_fake_capture()) == ""
    assert asr.finished
    assert engine._last_asr_end_reason == "initial_silence_timeout"
    assert statuses[-1] == "未检测到用户开口"


@pytest.mark.asyncio
async def test_speech_can_exceed_initial_window_but_stops_at_speech_maximum(monkeypatch) -> None:
    engine, _asr = _engine_with_fake_asr(monkeypatch, [
        (0.0, ASRResult(text="", speech_started=True)),
        (0.02, ASRResult(text="这是一个较长的问题", is_final=True)),
    ], initial=0.01, maximum=0.05)
    assert await engine._listen_cloud_asr(capture=_fake_capture()) == "这是一个较长的问题"

    timed_out, _asr = _engine_with_fake_asr(monkeypatch, [
        (0.0, ASRResult(text="", speech_started=True)),
    ], initial=0.01, maximum=0.01)
    assert await timed_out._listen_cloud_asr(capture=_fake_capture()) == ""
    assert timed_out._last_asr_end_reason == "speech_max_duration_timeout"



@pytest.mark.asyncio
async def test_local_endpoint_keeps_final_during_finalize_wait(monkeypatch) -> None:
    """FINAL that arrives after local endpoint must not be dropped as a timeout."""
    import chaihuo_reachy.engine as engine_module

    class Endpoint:
        vad = SimpleNamespace(available=True)

        def __init__(self, **_kwargs) -> None:
            pass

        def update(self, _chunk):
            return SimpleNamespace(
                rms=0.1,
                dbfs=-20.0,
                snr_db=15.0,
                vad_probability=0.9,
                speech=True,
                endpoint=True,
                endpoint_reason="local_silence",
            )

    monkeypatch.setattr(engine_module, "SpeechEndpoint", Endpoint)
    engine, asr = _engine_with_fake_asr(
        monkeypatch,
        [
            (0.0, ASRResult(text="", speech_started=True)),
            # Arrive after local endpoint has committed, during finalize wait.
            (0.05, ASRResult(text="皮皮虾，把昨天的这个行程再详细的说一说。", is_final=True)),
        ],
        maximum=0.5,
    )
    engine.config.asr_finalize_timeout_s = 0.2

    assert (
        await engine._listen_cloud_asr(capture=_fake_capture())
        == "皮皮虾，把昨天的这个行程再详细的说一说。"
    )
    assert engine._last_asr_end_reason == "completed"

@pytest.mark.asyncio
async def test_local_endpoint_commits_repeated_stable_partial(monkeypatch) -> None:
    import chaihuo_reachy.engine as engine_module

    class Endpoint:
        vad = SimpleNamespace(available=True)

        def __init__(self, **_kwargs) -> None:
            pass

        def update(self, _chunk):
            return SimpleNamespace(
                rms=0.1,
                dbfs=-20.0,
                snr_db=15.0,
                vad_probability=0.9,
                speech=True,
                endpoint=True,
                endpoint_reason="local_silence",
            )

    monkeypatch.setattr(engine_module, "SpeechEndpoint", Endpoint)
    engine, asr = _engine_with_fake_asr(
        monkeypatch,
        [
            (0.0, ASRResult(text="", speech_started=True)),
            (0.0, ASRResult(text="请介绍基地车")),
            (0.0, ASRResult(text="请介绍基地车")),
        ],
        maximum=1.0,
    )
    engine.config.asr_finalize_timeout_s = 0.01

    assert await engine._listen_cloud_asr(capture=_fake_capture()) == "请介绍基地车"
    assert asr.finished
    assert engine._last_asr_end_reason == "finalize_timeout"

def test_asr_client_uses_public_realtime_gateway() -> None:
    client = BailianASRClient(Config(bailian_asr_model="qwen3-asr-flash-realtime"))
    assert client._ws_url.startswith("wss://dashscope.aliyuncs.com/api-ws/v1/realtime")
    assert "model=qwen3-asr-flash-realtime" in client._ws_url


@pytest.mark.asyncio
async def test_asr_finish_commits_buffer_instead_of_closing_session() -> None:
    client = BailianASRClient(Config())
    websocket = _FakeWebSocket()
    client._ws = websocket  # type: ignore[assignment]
    client._connected = True
    await client.finish()
    assert websocket.messages[0]["type"] == "input_audio_buffer.commit"
    assert len(websocket.messages) == 1


@pytest.mark.asyncio
async def test_listen_reuses_startup_asr_connection(monkeypatch) -> None:
    engine, asr = _engine_with_fake_asr(
        monkeypatch,
        [
            (0.0, ASRResult(text="", speech_started=True)),
            (0.0, ASRResult(text="你好", is_final=True)),
        ],
    )
    assert await engine._listen_cloud_asr(capture=_fake_capture()) == "你好"
    assert asr.connect_calls == 1
    assert asr.close_calls == 0
    assert engine._asr is asr
    assert engine._asr.is_connected is True
    assert engine._asr_connect_count == 1

    asr.events = [
        (0.0, ASRResult(text="", speech_started=True)),
        (0.0, ASRResult(text="再见", is_final=True)),
    ]
    assert await engine._listen_cloud_asr(capture=_fake_capture()) == "再见"
    assert asr.connect_calls == 1
    assert asr.close_calls == 0
    assert engine._asr_connect_count == 1


@pytest.mark.asyncio
async def test_asr_reconnects_five_times_then_gives_up(monkeypatch) -> None:
    engine, asr = _engine_with_fake_asr(monkeypatch, [])
    engine.config.asr_reconnect_delay_s = 0.0
    engine.config.asr_reconnect_attempts = 5
    asr.fail_connects = 5
    with pytest.raises(ConnectionError, match="ASR handshake failed"):
        await engine._ensure_asr_connected()
    assert asr.connect_calls == 5
    assert engine._asr_connect_count == 0
    assert "handshake failed" in engine._asr_last_error


@pytest.mark.asyncio
async def test_asr_reconnects_after_drop_without_new_startup(monkeypatch) -> None:
    engine, asr = _engine_with_fake_asr(
        monkeypatch,
        [
            (0.0, ASRResult(text="", speech_started=True)),
            (0.0, ASRResult(text="继续", is_final=True)),
        ],
    )
    engine.config.asr_reconnect_delay_s = 0.0
    engine.config.asr_reconnect_attempts = 5
    assert await engine._listen_cloud_asr(capture=_fake_capture()) == "继续"
    asr.connected = False
    asr.fail_connects = 2
    asr.events = [
        (0.0, ASRResult(text="", speech_started=True)),
        (0.0, ASRResult(text="重连后", is_final=True)),
    ]
    assert await engine._listen_cloud_asr(capture=_fake_capture()) == "重连后"
    assert asr.connect_calls == 4
    assert engine._asr_reconnects == 1
    assert engine._asr_connect_count == 2

@pytest.mark.asyncio
async def test_recv_loop_disconnect_wakes_waiters_and_blocks_sends() -> None:
    client = BailianASRClient(Config())
    client._ws = object()  # type: ignore[assignment]
    client._connected = True
    client._notify_disconnect("ASR connection closed: no close frame received or sent")
    assert client.is_connected is False
    result = await asyncio.wait_for(client._result_queue.get(), timeout=0.1)
    assert "connection closed" in result.error
    with pytest.raises(ConnectionError, match="connection closed"):
        await client.send_audio(b"" * 320)


@pytest.mark.asyncio
async def test_ensure_reconnects_after_recv_loop_drop(monkeypatch) -> None:
    engine, asr = _engine_with_fake_asr(
        monkeypatch,
        [
            (0.0, ASRResult(text="", speech_started=True)),
            (0.0, ASRResult(text="重连后", is_final=True)),
        ],
    )
    await engine._ensure_asr_connected(initial=True)
    asr.connected = False
    await engine._ensure_asr_connected()
    assert asr.connect_calls == 2
    assert asr.is_connected is True

