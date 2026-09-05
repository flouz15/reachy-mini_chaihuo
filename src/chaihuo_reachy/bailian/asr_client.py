"""ASR WebSocket client for Bailian ``qwen3-asr-flash-realtime``.

Wire protocol (client → server):
  1. session.update — configure language, VAD, audio format
  2. input_audio_buffer.append — Base64-encoded PCM16 audio chunks
  3. input_audio_buffer.commit — end one utterance without closing the socket

Server events:
  - session.created / session.updated — handshake
  - input_audio_buffer.speech_started / .speech_stopped — VAD events
  - conversation.item.input_audio_transcription.text — interim (stash)
  - conversation.item.input_audio_transcription.completed — **final**

The demo keeps one WebSocket for the whole run.  ``connect()`` is called at
engine startup; later turns reuse the same session and only ``commit()`` the
current audio buffer.  ``session.finish`` is reserved for engine shutdown.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import uuid
from dataclasses import dataclass
from typing import AsyncIterator

import websockets
from websockets.exceptions import ConnectionClosed

from chaihuo_reachy.config import Config

logger = logging.getLogger("chaihuo_reachy.asr")
_PUBLIC_REALTIME_URL = "wss://dashscope.aliyuncs.com/api-ws/v1/realtime"


@dataclass
class ASRResult:
    """A single recognition result from the ASR service."""

    text: str
    is_final: bool = False
    speech_started: bool = False
    speech_stopped: bool = False
    error: str = ""


class BailianASRClient:
    """Async WebSocket client for Bailian realtime ASR.

    Usage::

        asr = BailianASRClient(cfg)
        await asr.connect()           # once at engine start
        await asr.send_audio(pcm)
        async for result in asr.results():
            if result.is_final:
                print(result.text)
        await asr.finish()            # commit this utterance
        await asr.close()             # only on engine stop
    """

    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg
        self._ws = None
        self._result_queue: asyncio.Queue[ASRResult] = asyncio.Queue(maxsize=64)
        self._recv_task: asyncio.Task | None = None
        self._close_timeout_s = 0.5
        self._connected = False
        self._session_id: str | None = None
        self._speech_start_time: float | None = None  # monotonic timestamp
        self._send_lock = asyncio.Lock()
        self._configured = asyncio.Event()
        self._handshake_error = ""
        self._last_disconnect = ""
        self._closing = False

    @property
    def is_connected(self) -> bool:
        return self._connected and self._ws is not None

    @property
    def _ws_url(self) -> str:
        # Public Realtime gateway — same host as Qwen TTS.  The workspace
        # MaaS host is for dedicated deployments and is a common source of
        # intermittent ASR handshake failures for the shared flash model.
        return f"{_PUBLIC_REALTIME_URL}?model={self._cfg.bailian_asr_model}"

    async def __aenter__(self) -> "BailianASRClient":
        await self.connect()
        return self

    async def __aexit__(self, *args) -> None:
        await self.close()

    async def connect(self) -> None:
        """Open the WebSocket and wait until session.updated arrives."""
        if self.is_connected:
            return
        await self.close()
        self._closing = False
        self._last_disconnect = ""
        self._result_queue = asyncio.Queue(maxsize=64)
        self._configured.clear()
        self._handshake_error = ""
        self._session_id = None
        timeout_s = max(1.0, float(self._cfg.asr_connect_timeout_s))
        self._ws = await websockets.connect(
            self._ws_url,
            additional_headers={
                "Authorization": f"Bearer {self._cfg.bailian_api_key}",
                "OpenAI-Beta": "realtime=v1",
            },
            ping_interval=20,
            ping_timeout=10,
            close_timeout=self._close_timeout_s,
            max_size=2**24,
            open_timeout=timeout_s,
        )
        self._connected = True
        self._recv_task = asyncio.create_task(self._recv_loop())
        logger.info("🔗 ASR WebSocket connected: %s", self._ws_url)
        await self.configure()
        try:
            await asyncio.wait_for(self._configured.wait(), timeout=timeout_s)
        except asyncio.TimeoutError as exc:
            await self.close()
            raise TimeoutError("ASR session handshake timed out") from exc
        if self._handshake_error:
            error = self._handshake_error
            await self.close()
            raise RuntimeError(error)

    async def close(self) -> None:
        self._closing = True
        was_connected = self._connected
        self._connected = False
        if self._recv_task is not None:
            self._recv_task.cancel()
            try:
                await self._recv_task
            except (asyncio.CancelledError, ConnectionClosed):
                pass
            self._recv_task = None
        if self._ws is not None:
            try:
                if was_connected:
                    event_id = f"evt_{uuid.uuid4().hex[:8]}"
                    await asyncio.wait_for(
                        self._ws.send(
                            json.dumps(
                                {"event_id": event_id, "type": "session.finish"},
                                ensure_ascii=False,
                            )
                        ),
                        timeout=self._close_timeout_s,
                    )
            except Exception:
                logger.debug("ASR session.finish on close failed", exc_info=True)
            try:
                await asyncio.wait_for(
                    self._ws.close(), timeout=self._close_timeout_s + 0.25
                )
            except asyncio.TimeoutError:
                logger.debug("ASR close handshake timed out — aborting")
                transport = getattr(self._ws, "transport", None)
                if transport is not None:
                    transport.abort()
            except Exception:
                logger.debug("ASR websocket close failed", exc_info=True)
            self._ws = None

    async def configure(self) -> None:
        """Send session.update to configure ASR."""
        event_id = f"evt_{uuid.uuid4().hex[:8]}"
        msg = {
            "event_id": event_id,
            "type": "session.update",
            "session": {
                "input_audio_format": "pcm",
                "sample_rate": self._cfg.audio_sample_rate,
                "input_audio_transcription": {
                    "language": self._cfg.asr_language,
                },
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": self._cfg.asr_vad_threshold,
                    "silence_duration_ms": self._cfg.asr_vad_silence_ms,
                },
            },
        }
        await self._send(msg)

    async def send_audio(self, pcm_bytes: bytes) -> None:
        """Send a PCM16 mono audio chunk (Base64-encoded internally)."""
        event_id = f"evt_{uuid.uuid4().hex[:8]}"
        msg = {
            "event_id": event_id,
            "type": "input_audio_buffer.append",
            "audio": base64.b64encode(pcm_bytes).decode(),
        }
        await self._send(msg)

    async def finish(self) -> None:
        """Commit the current utterance; keep the WebSocket open."""
        event_id = f"evt_{uuid.uuid4().hex[:8]}"
        await self._send({"event_id": event_id, "type": "input_audio_buffer.commit"})

    def reset_turn(self) -> None:
        """Drop stale events so the next listen starts from a clean queue."""
        while True:
            try:
                self._result_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    async def results(self) -> AsyncIterator[ASRResult]:
        """Yield ASR results as they arrive for the current utterance."""
        while True:
            result = await self._result_queue.get()
            yield result
            if result.is_final or result.error:
                return

    async def _send(self, msg: dict) -> None:
        if not self.is_connected:
            raise ConnectionError(self._last_disconnect or "ASR client not connected")
        assert self._ws is not None
        async with self._send_lock:
            try:
                await self._ws.send(json.dumps(msg, ensure_ascii=False))
            except Exception as exc:
                self._notify_disconnect(f"ASR send failed: {exc}")
                raise ConnectionError(self._last_disconnect) from exc

    def _notify_disconnect(self, error: str) -> None:
        """Mark the socket dead and wake any listen waiters."""
        if self._closing:
            self._connected = False
            return
        if not self._connected and self._last_disconnect:
            return
        self._connected = False
        self._last_disconnect = error
        logger.warning("ASR 连接已断开: %s", error)
        self._put_result(ASRResult(text="", error=error))

    def _put_result(self, result: ASRResult) -> None:
        try:
            self._result_queue.put_nowait(result)
        except asyncio.QueueFull:
            try:
                self._result_queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                self._result_queue.put_nowait(result)
            except asyncio.QueueFull:
                pass

    async def _recv_loop(self) -> None:
        assert self._ws is not None
        try:
            async for raw in self._ws:
                msg = json.loads(raw)
                await self._dispatch(msg)
            if self._connected:
                self._notify_disconnect("ASR connection closed")
        except asyncio.CancelledError:
            raise
        except ConnectionClosed as e:
            self._notify_disconnect(f"ASR connection closed: {e}")
        except Exception as exc:
            logger.exception("ASR recv loop error")
            self._notify_disconnect(f"ASR recv loop error: {exc}")

    async def _dispatch(self, msg: dict) -> None:
        import time as _time
        msg_type = msg.get("type", "")

        if msg_type == "input_audio_buffer.speech_started":
            self._speech_start_time = _time.monotonic()
            logger.info("🟢 [VAD] speech_started — 检测到语音")
            await self._result_queue.put(
                ASRResult(text="", speech_started=True)
            )
        elif msg_type == "input_audio_buffer.speech_stopped":
            duration_s = ""
            if self._speech_start_time is not None:
                d = _time.monotonic() - self._speech_start_time
                duration_s = f" (持续 {d:.1f}s)"
                self._speech_start_time = None
            logger.info("🛑 [VAD] speech_stopped — 语音结束%s", duration_s)
            await self._result_queue.put(
                ASRResult(text="", speech_stopped=True)
            )
        elif msg_type == "conversation.item.input_audio_transcription.text":
            stash = msg.get("stash", "")
            if stash:
                logger.debug("📝 [ASR] partial: %r", stash)
                await self._result_queue.put(ASRResult(text=stash))
        elif msg_type == "conversation.item.input_audio_transcription.completed":
            transcript = msg.get("transcript", "")
            logger.info("✅ [ASR] FINAL: %r", transcript)
            await self._result_queue.put(
                ASRResult(
                    text=transcript,
                    is_final=True,
                )
            )
        elif msg_type == "session.created":
            self._session_id = msg.get("session", {}).get("id", "?")
            logger.info("🔗 ASR session created: %s", self._session_id)
        elif msg_type == "session.updated":
            self._configured.set()
            logger.info(
                "⚙️  [ASR] configured (VAD=%.1f threshold, %dms silence, lang=%s)",
                self._cfg.asr_vad_threshold,
                self._cfg.asr_vad_silence_ms,
                self._cfg.asr_language,
            )
        elif msg_type == "session.finished":
            logger.info("🔌 ASR session finished")
            self._notify_disconnect("ASR session finished")
        elif msg_type == "error":
            error = str(msg.get("error", msg))
            logger.error("❌ ASR error: %s", error)
            if not self._configured.is_set():
                self._handshake_error = error
                self._configured.set()
            await self._result_queue.put(ASRResult(text="", error=error))
        else:
            logger.debug("ASR unhandled: %s", msg_type)
