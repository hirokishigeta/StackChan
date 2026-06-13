"""WebSocket audio endpoint ``WS /api/bot/{device_id}/audio`` (Issue #7-a).

xiaozhi-compatible wire protocol (docs/backend-protocol.md §2/§3, ADR-0004):

- ``hello`` handshake: client ``hello`` (audio_params) -> server ``hello``
  (session_id + downlink audio_params).
- control JSON: ``listen`` (start/stop/detect), ``abort``, ``mcp``.
- uplink binary Opus frames -> decode (AudioDecoder port) -> ASR
  (SpeechRecognizer port) -> reply via AgentGateway.chat -> downlink control
  JSON ``stt`` (user text) / ``llm`` (emotion) / ``tts`` (sentence_start text).

#7-b adds the downlink TTS *audio* frames between ``tts.start`` and ``tts.stop``:
reply text -> SpeechSynthesizer port (text [+emotion] -> PCM) -> resample to the
negotiated downlink rate -> AudioEncoder port (PCM -> Opus) -> binary frames via
``encode_frame``. If synthesis/encoding is unavailable, the turn degrades to
text only (the #7-a behaviour) and the connection stays alive (design-spec §13).

This layer is presentation only: it calls application ports resolved by the
container; no business logic lives here (CLAUDE.md layer rules).
"""

from __future__ import annotations

import logging
import math
import struct
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.application.ports.agent_gateway import AgentError, AgentGateway
from app.application.ports.audio_decoder import AudioDecodeError, AudioDecoder
from app.application.ports.audio_encoder import AudioEncodeError, AudioEncoder
from app.application.ports.settings_repository import SettingsRepository
from app.application.ports.speech_recognizer import SpeechRecognizer
from app.application.ports.speech_synthesizer import SpeechSynthesisError, SpeechSynthesizer
from app.config.settings import AppSettings
from app.di_container import container as container_module
from app.domain.agent.entities import AgentProfile
from app.domain.agent.value_objects import AgentReply
from app.domain.speech.entities import SpeechRecognitionConfig
from app.domain.speech.value_objects import AudioFormat
from app.infrastructure.audio.resample import resample_pcm16
from app.infrastructure.transport.audio_frame_codec import (
    AudioFrameError,
    decode_frame,
    encode_frame,
)

router = APIRouter(prefix="/api/bot", tags=["bot-audio"])

# Use uvicorn's logger so these diagnostics are visible under `uvicorn` without
# extra logging config (the default config does not surface arbitrary loggers).
logger = logging.getLogger("uvicorn.error")


@dataclass
class _VadState:
    """Energy-based end-of-utterance detection state for one utterance.

    Tracks how much speech and trailing silence we've seen so we can decide when
    the user has stopped talking (xiaozhi `listen mode:auto`, design-spec §7.5).
    Durations are accumulated in milliseconds from each frame's PCM length so the
    detector is independent of the negotiated frame size.
    """

    speech_ms: float = 0.0
    silence_ms: float = 0.0
    utterance_ms: float = 0.0
    in_speech: bool = False

    def reset(self) -> None:
        self.speech_ms = 0.0
        self.silence_ms = 0.0
        self.utterance_ms = 0.0
        self.in_speech = False


@dataclass
class _Session:
    """Per-connection state for one device's audio channel."""

    device_id: str
    session_id: str
    binary_version: int = 0
    audio_format: AudioFormat = AudioFormat()
    listening: bool = False
    aborted: bool = False
    frames_rx: int = 0
    # xiaozhi listen mode of the current turn ("auto" | "manual" | "realtime").
    # Only "auto" relies on server-side VAD; "manual" finalizes on `listen stop`.
    listen_mode: str = "manual"
    # True while a turn is being spoken (tts.start..stop). Used for half-duplex
    # gating: uplink audio is dropped so the bot's own voice (no device AEC)
    # does not re-trigger VAD into an echo loop.
    speaking: bool = False
    vad: _VadState = field(default_factory=_VadState)
    pcm_buffer: bytearray = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.pcm_buffer is None:
            self.pcm_buffer = bytearray()


class BotAudioHandler:
    """Drives one WS audio session against the application ports.

    Constructed per connection with ports injected (testable with fakes).
    """

    def __init__(
        self,
        *,
        settings: AppSettings,
        speech_recognizer: SpeechRecognizer,
        agent_gateway: AgentGateway,
        audio_decoder: AudioDecoder,
        speech_synthesizer: SpeechSynthesizer,
        audio_encoder: AudioEncoder,
        repository: SettingsRepository,
    ) -> None:
        self._settings = settings
        self._asr = speech_recognizer
        self._agent = agent_gateway
        self._decoder = audio_decoder
        self._synthesizer = speech_synthesizer
        self._encoder = audio_encoder
        self._repository = repository

    async def run(self, websocket: WebSocket, device_id: str) -> None:
        await websocket.accept()
        session = _Session(device_id=device_id, session_id=uuid.uuid4().hex)
        logger.info("WS connect device=%s session=%s", device_id, session.session_id)
        try:
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    return
                if message.get("text") is not None:
                    await self._on_text(websocket, session, message["text"])
                elif message.get("bytes") is not None:
                    await self._on_binary(websocket, session, message["bytes"])
        except WebSocketDisconnect:
            return

    # -- text (control JSON) ------------------------------------------------

    async def _on_text(self, ws: WebSocket, session: _Session, raw: str) -> None:
        import json

        try:
            msg: dict[str, Any] = json.loads(raw)
        except (ValueError, TypeError):
            # Malformed control message: ignore, keep the connection alive
            # (design-spec §13). A single bad frame must not kill the session.
            return
        handler = self._CONTROL_HANDLERS.get(str(msg.get("type")))
        if handler is None:
            return
        await handler(self, ws, session, msg)

    async def _handle_hello(self, ws: WebSocket, session: _Session, msg: dict[str, Any]) -> None:
        session.binary_version = int(msg.get("version", 0) or 0)
        logger.info(
            "hello: bin_ver=%d audio_params=%r", session.binary_version, msg.get("audio_params")
        )
        params = msg.get("audio_params") or {}
        session.audio_format = AudioFormat(
            codec=str(params.get("format", "opus")),
            sample_rate=int(params.get("sample_rate", self._settings.uplink_sample_rate)),
            channels=int(params.get("channels", self._settings.uplink_channels)),
            frame_duration_ms=int(
                params.get("frame_duration", self._settings.uplink_frame_duration_ms)
            ),
        )
        await ws.send_json(
            {
                "type": "hello",
                "transport": "websocket",
                "session_id": session.session_id,
                "audio_params": {
                    "sample_rate": self._settings.downlink_sample_rate,
                    "frame_duration": self._settings.downlink_frame_duration_ms,
                },
            }
        )

    async def _handle_listen(self, ws: WebSocket, session: _Session, msg: dict[str, Any]) -> None:
        state = str(msg.get("state"))
        logger.info("listen msg=%r", msg)
        if state == "start":
            session.listening = True
            session.aborted = False
            session.frames_rx = 0
            session.pcm_buffer = bytearray()
            # mode defaults to "manual" so an absent field never silently turns
            # on VAD; real auto-mode devices always send mode:"auto" (§6).
            session.listen_mode = str(msg.get("mode", "manual"))
            session.vad.reset()
        elif state == "stop":
            # Manual mode: the device tells us when the utterance ends. (Auto-mode
            # devices never send stop; the VAD path in _on_binary finalizes them.)
            session.listening = False
            await self._finalize_turn(ws, session)
        elif state == "detect":
            # Wake-word detect carries text; treat it as the utterance so a
            # turn can start without uplink audio (docs/backend-protocol.md §2.1).
            # detect begins a *new* turn, so clear any prior abort flag — else a
            # turn that follows an abort emits `stt` then silently drops the
            # `llm`/`tts` response (the abort guard in _run_agent_turn fires),
            # leaving the device waiting forever.
            text = str(msg.get("text", ""))
            if text:
                session.aborted = False
                await self._run_agent_turn(ws, session, text)

    async def _handle_abort(self, ws: WebSocket, session: _Session, msg: dict[str, Any]) -> None:
        # Barge-in: drop in-progress audio and stop any speaking turn (§6).
        session.aborted = True
        session.listening = False
        session.pcm_buffer = bytearray()
        await ws.send_json({"type": "tts", "state": "stop"})

    async def _handle_mcp(self, ws: WebSocket, session: _Session, msg: dict[str, Any]) -> None:
        # Echo MCP control payloads back as a well-formed mcp message so the
        # device control RPC path is wired end-to-end (minimal for #7-a).
        # TODO(issue#7b): route through BotEventPublisher / McpServer commands.
        payload = msg.get("payload")
        if payload is not None:
            await ws.send_json(
                {"type": "mcp", "session_id": session.session_id, "payload": payload}
            )

    _CONTROL_HANDLERS: dict[str, Any] = {
        "hello": _handle_hello,
        "listen": _handle_listen,
        "abort": _handle_abort,
        "mcp": _handle_mcp,
    }

    # -- binary (uplink audio) ----------------------------------------------

    async def _on_binary(self, ws: WebSocket, session: _Session, data: bytes) -> None:
        if not session.listening or session.aborted:
            return
        # Half-duplex: while the bot is speaking, drop uplink audio so its own
        # TTS voice (CoreS3 has no AEC) does not feed VAD into an echo loop, and
        # a new turn cannot start re-entrantly mid-reply. Barge-in still arrives
        # as an `abort`/`listen` control (text), which is not gated here.
        if session.speaking and self._settings.tts_half_duplex:
            return
        try:
            payload = decode_frame(data=data, version=session.binary_version)
            pcm = self._decoder.decode(payload=payload, audio_format=session.audio_format)
        except (AudioFrameError, AudioDecodeError) as exc:
            # Corrupt frame / missing codec: skip it, keep the session alive.
            logger.warning(
                "binary decode failed (v=%s,%dB): %s", session.binary_version, len(data), exc
            )
            return
        session.frames_rx += 1
        if session.frames_rx == 1 or session.frames_rx % 25 == 0:
            logger.info(
                "audio frame #%d (+%dB pcm, buf=%dB)",
                session.frames_rx,
                len(pcm),
                len(session.pcm_buffer) + len(pcm),
            )
        session.pcm_buffer.extend(pcm)
        await self._run_vad(ws, session, pcm)

    # -- server-side VAD (end-of-utterance for listen mode:auto) ------------

    @staticmethod
    def _rms16(pcm: bytes) -> float:
        """RMS amplitude of 16-bit LE mono PCM (0..32767). Empty -> 0."""
        n = len(pcm) // 2
        if n == 0:
            return 0.0
        samples = struct.unpack(f"<{n}h", pcm[: n * 2])
        return math.sqrt(sum(s * s for s in samples) / n)

    async def _run_vad(self, ws: WebSocket, session: _Session, pcm: bytes) -> None:
        """Detect end-of-utterance by energy and finalize (auto mode only).

        Speech (RMS >= threshold) extends the utterance; once enough speech has
        been seen, a run of trailing silence (>= silence_ms) finalizes the turn.
        A max-utterance cap force-finalizes runaway streams. After finalizing we
        keep ``listening`` True and reset VAD state to await the next utterance,
        because auto-mode connections stay open across turns (design-spec §7.5).
        """
        settings = self._settings
        if not settings.vad_enabled or session.listen_mode != "auto":
            return
        # Frame duration derived from sample length so VAD is frame-size agnostic.
        sample_rate = session.audio_format.sample_rate or settings.uplink_sample_rate
        n_samples = len(pcm) // 2
        if sample_rate <= 0 or n_samples == 0:
            return
        frame_ms = n_samples * 1000.0 / sample_rate

        vad = session.vad
        vad.utterance_ms += frame_ms
        is_speech = self._rms16(pcm) >= settings.vad_rms_threshold
        if is_speech:
            if not vad.in_speech and vad.speech_ms == 0.0:
                logger.info("VAD: speech start")
            vad.in_speech = True
            vad.speech_ms += frame_ms
            vad.silence_ms = 0.0
        else:
            vad.silence_ms += frame_ms

        ended_on_silence = (
            vad.speech_ms >= settings.vad_min_speech_ms
            and vad.silence_ms >= settings.vad_silence_ms
        )
        forced = vad.utterance_ms >= settings.vad_max_utterance_ms
        if not (ended_on_silence or forced):
            return

        reason = "max-utterance" if forced and not ended_on_silence else "silence"
        logger.info(
            "VAD: end-of-utterance (%s) -> finalize buf=%dB",
            reason,
            len(session.pcm_buffer),
        )
        # On a forced cut with no detected speech, the buffer is just noise/silence:
        # reset without invoking ASR to avoid empty-ASR spam (requirement 8).
        if forced and vad.speech_ms < settings.vad_min_speech_ms:
            session.pcm_buffer = bytearray()
            vad.reset()
            return
        vad.reset()
        # Stay listening: auto-mode keeps streaming for the next utterance.
        await self._finalize_turn(ws, session)

    # -- turn handling ------------------------------------------------------

    async def _finalize_turn(self, ws: WebSocket, session: _Session) -> None:
        if session.aborted:
            return
        # Drop a finalize that races a turn already in flight (half-duplex).
        if session.speaking:
            return
        audio = bytes(session.pcm_buffer)
        session.pcm_buffer = bytearray()
        logger.info("finalize: pcm=%d bytes", len(audio))
        config = SpeechRecognitionConfig(
            provider=self._settings.default_speech_provider,
            language=self._settings.default_speech_language,
        )
        try:
            result = await self._asr.recognize(audio=audio, config=config)
        except Exception:  # noqa: BLE001 - ASR failure must not kill the session
            logger.exception("ASR failed")
            await ws.send_json({"type": "tts", "state": "stop"})
            return
        logger.info("stt=%r", result.text)
        if not result.text:
            await ws.send_json({"type": "tts", "state": "stop"})
            return
        await self._run_agent_turn(ws, session, result.text)

    async def _run_agent_turn(self, ws: WebSocket, session: _Session, user_text: str) -> None:
        # Recognized user text (xiaozhi `stt`, §2.2).
        await ws.send_json({"type": "stt", "text": user_text})
        logger.info("agent_turn user=%r", user_text)
        profile = self._resolve_profile(session.device_id)
        try:
            reply = await self._agent.chat(message=user_text, profile=profile, context=None)
        except AgentError as exc:
            # Safe fallback (ADR-0005 / design-spec §13): keep the loop alive.
            logger.warning("agent error -> safe fallback (LLM未設定/失敗?): %s", exc)
            await ws.send_json({"type": "tts", "state": "stop"})
            return
        logger.info("reply emotion=%s text=%r", reply.emotion, reply.text)
        if session.aborted:
            return
        # Emotion -> expression (xiaozhi `llm`, §2.2 -> firmware SetEmotion).
        await ws.send_json({"type": "llm", "emotion": reply.emotion})
        # Half-duplex: mark speaking across the whole tts.start..stop window so
        # the bot's own voice (no device AEC) is not heard back as input. On exit
        # reset VAD/buffer so the in-flight tail (captured just before the gate
        # closed) cannot immediately re-finalize once we re-open the mic.
        session.speaking = True
        try:
            # tts.start -> (downlink Opus audio frames) -> sentence_start text ->
            # tts.stop. The audio frames are #7-b; the JSON sequence is unchanged
            # from #7-a so the device's existing path keeps working.
            await ws.send_json({"type": "tts", "state": "start"})
            await ws.send_json({"type": "tts", "state": "sentence_start", "text": reply.text})
            await self._send_tts_audio(ws, session, reply)
            await ws.send_json({"type": "tts", "state": "stop"})
        finally:
            session.speaking = False
            session.vad.reset()
            session.pcm_buffer = bytearray()

    async def _send_tts_audio(self, ws: WebSocket, session: _Session, reply: AgentReply) -> None:
        """Synthesize the reply and send downlink Opus frames (#7-b).

        On any synthesis/encoding failure (engine not installed, model unset,
        codec missing) this degrades to a text-only turn: the JSON stream is
        already complete, so we simply skip the audio and keep the connection
        alive (design-spec §13).
        """
        downlink = AudioFormat(
            codec="opus",
            sample_rate=self._settings.downlink_sample_rate,
            channels=self._settings.downlink_channels,
            frame_duration_ms=self._settings.downlink_frame_duration_ms,
        )
        try:
            audio = self._synthesizer.synthesize(text=reply.text, emotion=reply.emotion)
            pcm = resample_pcm16(
                pcm=audio.pcm,
                src_rate=audio.sample_rate,
                dst_rate=downlink.sample_rate,
            )
            payloads = self._encoder.encode(pcm=pcm, audio_format=downlink)
        except (SpeechSynthesisError, AudioEncodeError, ValueError) as exc:
            # Text-only fallback (#7-a behaviour). Connection stays alive, but
            # log loudly: a swallowed encode/synth error means silent playback.
            logger.warning("TTS downlink skipped (text-only fallback): %s", exc)
            return
        logger.info(
            "TTS downlink: synth=%dB@%dHz -> resampled=%dB@%dHz -> %d opus frame(s), bin_ver=%d",
            len(audio.pcm),
            audio.sample_rate,
            len(pcm),
            downlink.sample_rate,
            len(payloads),
            session.binary_version,
        )
        sent = 0
        for payload in payloads:
            if session.aborted:
                break
            frame = encode_frame(payload=payload, version=session.binary_version)
            await ws.send_bytes(frame)
            sent += 1
        logger.info("TTS downlink: sent %d/%d frame(s)", sent, len(payloads))

    def _resolve_profile(self, device_id: str) -> AgentProfile:
        settings = self._repository.get_settings(device_id)
        return settings.agent if settings is not None else AgentProfile()


@router.websocket("/{device_id}/audio")
async def bot_audio(websocket: WebSocket, device_id: str) -> None:
    """xiaozhi-compatible audio channel (docs/backend-protocol.md §4.1)."""
    container = container_module.get_container()
    # Opus enc/dec are stateful per stream; give this connection its own
    # session-scoped instances so concurrent devices never share libopus state
    # (Issue #27). Stateless codecs (raw) return the shared instance unchanged.
    handler = BotAudioHandler(
        settings=container.settings,
        speech_recognizer=container.speech_recognizer,
        agent_gateway=container.agent_gateway,
        audio_decoder=container.audio_decoder.for_session(),
        speech_synthesizer=container.speech_synthesizer,
        audio_encoder=container.audio_encoder.for_session(),
        repository=container.repository,
    )
    await handler.run(websocket, device_id)
