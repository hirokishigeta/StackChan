"""Application configuration.

Values come from environment variables (prefix ``STACKCHAN_``) or defaults.
This module is referenceable from any layer (see CLAUDE.md dependency rules).
No hard-coded URLs / model names live outside of this module.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

# Shared single source of truth for the default JP end-word list (ADR-0016).
# config may reference domain (domain depends on nothing, so there is no cycle).
from app.domain.wakeword.entities import DEFAULT_END_WORD_PHRASES


class AppSettings(BaseSettings):
    """Runtime settings, overridable via environment variables.

    Example: ``STACKCHAN_DATABASE_URL=sqlite:///./prod.db``.
    """

    model_config = SettingsConfigDict(env_prefix="STACKCHAN_", env_file=".env", extra="ignore")

    app_name: str = "StackChan Backend"
    # SQLite by default; private-network local AI backend (design-spec §10).
    database_url: str = "sqlite:///./stackchan.db"

    # Dashboard default device id (settings UI prefill). Not a security boundary;
    # the dashboard is LAN-only (design-spec §13). Configurable, not hard-coded.
    dashboard_default_device_id: str = "cores3-001"

    # CORS: LAN-only by default (design-spec §13 security).
    cors_allow_origins: list[str] = ["*"]

    # OTA check / provisioning endpoint (Issue #23, docs/backend-protocol.md §5.3).
    # The firmware's Ota::CheckVersion POSTs to wifi.ota_url (pointed here by #5);
    # the backend answers with a xiaozhi-compatible `websocket` section so the
    # device picks WebsocketProtocol in Application::InitializeProtocol. These
    # values build the WS URL returned to the device and are never hard-coded in
    # the route (CLAUDE.md).
    #
    # ws_public_scheme/host/port build:
    #   <scheme>://<host>:<port><ws_path_prefix>/<device_id>/audio
    # host defaults to a placeholder that MUST be overridden in deployment with
    # the backend's LAN-reachable address (a device cannot reach "localhost").
    ota_ws_scheme: str = "ws"
    ota_ws_host: str = "127.0.0.1"
    ota_ws_port: int = 8000
    # Path prefix of the audio WS endpoint (matches bot_audio_ws router prefix).
    ota_ws_path_prefix: str = "/api/bot"
    # Protocol-Version advertised to the device (websocket.version). 2 keeps the
    # binary frame timestamp field for server-side AEC (backend-protocol.md §3.1).
    ota_ws_version: int = 2
    # Optional bearer token written to the device's websocket.token. Empty means
    # no Authorization header on the audio WS (websocket_protocol.cc:101-107).
    ota_ws_token: str = ""

    # Agent provider selection (resolved via a registry in di_container; the
    # value must match an AgentType, e.g. "OpenAICompatible"). No if-based
    # provider branching (CLAUDE.md / design-spec §13).
    default_agent_type: str = "OpenAICompatible"
    default_agent_model: str = "dummy-model"

    # OpenAI-compatible Gateway (design-spec §11.3). base_url / api_key / model
    # are never hard-coded outside this module (CLAUDE.md).
    agent_base_url: str = "http://localhost:11434/v1"
    agent_api_key: str = ""
    # Per-request timeout in seconds. On timeout the gateway raises AgentError
    # and the API returns a safe fallback so the conversation loop survives.
    agent_request_timeout_s: float = 30.0

    # Speech (ASR) provider, resolved via a registry in di_container. Default
    # is "dummy" so the process / make check run without native deps or models;
    # set "sherpa-onnx" in deployment (CLAUDE.md: registry, not if-branching).
    default_speech_provider: str = "dummy"
    default_speech_language: str = "ja"

    # sherpa-onnx model paths and runtime (no hard-coded paths; CLAUDE.md).
    # Empty by default: SherpaOnnxSpeechRecognizer raises a clear error if used
    # without these set (lazy-loaded, never at import time).
    sherpa_tokens_path: str = ""
    sherpa_encoder_path: str = ""
    sherpa_decoder_path: str = ""
    sherpa_joiner_path: str = ""
    sherpa_sample_rate: int = 16000
    sherpa_num_threads: int = 1

    # Uplink audio decoder (Opus -> PCM), resolved via a registry. Default is
    # "raw" (PCM pass-through) so the WS server runs without libopus; set
    # "opus" once the optional [opus] extra is installed
    # (docs/backend-protocol.md §3). Uplink Opus default: 16 kHz / mono / 60 ms.
    audio_decoder: str = "raw"
    uplink_sample_rate: int = 16000
    uplink_channels: int = 1
    uplink_frame_duration_ms: int = 60

    # Server-side VAD (end-of-utterance detection) for xiaozhi `listen mode:auto`
    # (docs/backend-protocol.md §6, design-spec §7.5). Real devices in `auto` mode
    # never send `listen stop`; they stream PCM and expect the *server* to detect
    # the end of the utterance and run ASR -> agent -> reply. We do an energy (RMS)
    # based VAD on the decoded 16-bit LE mono PCM, with no external model. These
    # are config (no hard-coded thresholds; CLAUDE.md). `manual` mode is unaffected:
    # it finalizes on `listen stop` exactly as before.
    vad_enabled: bool = True
    # RMS amplitude threshold (0..32767). A frame at/above this counts as speech.
    vad_rms_threshold: int = 500
    # Minimum cumulative speech before a trailing silence can finalize a turn.
    # Guards against finalizing on a brief noise spike (avoids empty-ASR spam).
    vad_min_speech_ms: int = 300
    # Trailing silence (hangover) after speech that triggers end-of-utterance.
    vad_silence_ms: int = 800
    # Safety cap: force end-of-utterance once an utterance reaches this length.
    vad_max_utterance_ms: int = 15000
    # Half-duplex: drop uplink audio while the bot is speaking (tts.start..stop).
    # CoreS3 has no acoustic echo cancellation, so in auto mode the mic would
    # otherwise pick up the bot's own TTS voice and re-trigger VAD (echo loop).
    # Barge-in still works: the device sends an explicit `abort`/`listen` control
    # (not gated here). Set False only on hardware with reliable AEC.
    tts_half_duplex: bool = True
    # Keep the half-duplex mic gate closed this long AFTER tts.stop. The device
    # buffers downlink audio and keeps playing past tts.stop, so reopening the
    # mic immediately captures that tail as echo (no device AEC) — seen as a
    # doubled/garbled next utterance. Should cover the device's buffer depth.
    tts_postroll_gate_ms: int = 1500

    # Backend-side wake-word gating (ADR-0014). When the firmware streams audio
    # continuously (VAD-gated, no on-device wake word), the backend decides when
    # to engage: a finalized utterance is only handed to the agent once it
    # contains one of the device's configured wake words (matched on the STT
    # transcript text — arbitrary Japanese, no extra model). Default OFF so the
    # current on-device-wake behavior is unchanged until the firmware is ready.
    wake_word_gate_enabled: bool = False
    # Fuzzy (edit-distance) wake-word matching cap (ADR-0018). The backend STT
    # mis-transcribes the wake word wildly (e.g. "ベルちゃん" heard as
    # "ねるちゃん"/"ピルちゃん"), and enumerating every variant is infeasible. With
    # this > 0 the gate also matches when a window of the transcript is within a
    # length-scaled Levenshtein distance (1 for 3-4 char phrases, 2 for >=5;
    # capped here) of a configured phrase, and the fuzzy span is corrected to the
    # canonical name before the agent sees it. Short phrases (<=2 chars) stay
    # exact-only regardless. 0 disables fuzzy entirely (exact/substring behavior).
    wake_fuzzy_max_dist: int = 2
    # Once engaged, the conversation stays open without re-saying the wake word
    # until this much wall-clock idle time passes between processed turns; after
    # that the gate disengages and the next utterance must include a wake word.
    wake_idle_timeout_ms: int = 30000
    # End-of-conversation words: while engaged, an utterance containing any of
    # these ends the conversation (in addition to the agent's own end_conversation
    # judgment). The bot gives a brief farewell, then disengages and returns to
    # wake-waiting (next turn needs the wake word again). Matched on STT text.
    # This is the GLOBAL fallback used when a device has no per-device end words
    # configured (ADR-0016); the per-device list is the primary source.
    conversation_end_words: list[str] = list(DEFAULT_END_WORD_PHRASES)

    # Downlink (server -> device) audio_params returned in the server hello.
    # These values are negotiated so firmware (#5) can rely on them; the
    # downlink TTS audio path (#7-b) resamples/encodes to these.
    downlink_sample_rate: int = 24000
    downlink_channels: int = 1
    downlink_frame_duration_ms: int = 60
    # Downlink TTS frames are paced at real time (deadline-scheduled) so the
    # device's jitter buffer neither overflows (flooding -> dropped frames) nor
    # underruns (drift -> crackle). This many frames are sent up front as a
    # cushion to absorb per-frame jitter; the rest follow on a monotonic
    # deadline. ~15 * 60ms = ~900ms of lead. Larger = more jitter tolerance but
    # later barge-in and more buffered audio on the device.
    downlink_prime_frames: int = 15
    # Silence (ms) prepended to each TTS reply. The CoreS3 drops a fixed window
    # (~1s) at playback start — its audio pipeline takes ~1s to start producing
    # sound after entering the speaking state (confirmed via serial log + on-
    # device A/B: 800ms still clipped, 1200ms played the opening cleanly; the
    # synthesized audio itself is complete and amp/firmware warm-up did not help).
    # This silence absorbs that drop instead of the opening syllable. With the
    # synth-bridge (see _send_tts_audio) this is the *minimum* bridge silence:
    # the device plays silence for max(synth_time, this) before the real audio,
    # so the synth-wait and the start-drop overlap rather than stacking. Tune per
    # deployment (trade latency vs safety).
    downlink_lead_silence_ms: int = 1200
    # Safety cap on the silence bridge so a hung/slow synth can't stream silence
    # forever before falling back to text-only.
    tts_max_bridge_ms: int = 6000

    # Downlink audio encoder (PCM -> Opus), resolved via a registry. Default is
    # "raw" (PCM pass-through, framed) so the WS server runs without libopus;
    # set "opus" once the optional [opus] extra is installed
    # (docs/backend-protocol.md §3). No if-branching (CLAUDE.md).
    audio_encoder: str = "raw"

    # Vision recognizer provider, resolved via a registry in di_container.
    # Default is "dummy" so the process / make check run without OpenCV or any
    # model; set "opencv" once the optional [vision] extra is installed
    # (CLAUDE.md: registry, not if-branching).
    default_vision_provider: str = "dummy"
    # OpenCV Haar cascade path (no hard-coded paths; CLAUDE.md). Empty means use
    # OpenCV's bundled frontal-face cascade. OpenCvFaceDetector raises a clear
    # error if the cascade cannot be loaded (lazy, never at import time).
    opencv_face_cascade_path: str = ""
    opencv_scale_factor: float = 1.1
    opencv_min_neighbors: int = 5
    # Debug: when set, /api/vision/detect writes each received image to this
    # path (overwritten each call) so the camera feed can be inspected. Empty
    # disables. For diagnostics only.
    vision_debug_save_path: str = ""

    # TTS (downlink speech synthesis) provider, resolved via a registry. Default
    # is "dummy" so the process / make check run without heavy deps or models;
    # set "irodori" in deployment (ADR-0006). The WS loop falls back to a
    # text-only turn if synthesis is unavailable (design-spec §13).
    default_tts_provider: str = "dummy"
    # Preload the TTS runtime at app startup (in a background thread, never
    # blocking startup) so the first conversation turn doesn't pay the one-time
    # model-load latency. No-op for lightweight engines (dummy).
    tts_warm_up_on_startup: bool = True

    # Irodori-TTS (ADR-0006). Heavy deps (PyTorch / HF checkpoint) are optional
    # and lazy-loaded; paths/device come from here (no hard-coded paths,
    # CLAUDE.md). Empty by default: IrodoriTtsSynthesizer raises a clear error
    # if used without these set. Irodori emits 48 kHz audio.
    irodori_model_path: str = ""
    irodori_reference_wav_path: str = ""
    # Directory of pre-generated voice samples (one .wav = one selectable
    # reference voice; ADR-0012). The dashboard lists these; selecting one fixes
    # the cloned TTS timbre. ``~`` is expanded by the repository. The wavs are
    # generated separately on the GPU host into this directory (no hard-coded
    # paths; CLAUDE.md).
    voice_samples_dir: str = "~/.stackchan/voice_samples"
    irodori_device: str = "cpu"
    irodori_sample_rate: int = 48000
    # Codec / precision for the Irodori InferenceRuntime (match infer.py argparse
    # defaults; ADR-0006). codec runs on CPU by default to keep VRAM for the model.
    irodori_codec_repo: str = "Aratako/Semantic-DACVAE-Japanese-32dim"
    irodori_model_precision: str = "fp32"
    irodori_codec_device: str = "cpu"
    irodori_codec_precision: str = "fp32"
    # Persona base style emoji prepended to every utterance.
    # Empty disables the base. Per-emotion emoji are appended on top (see
    # app.infrastructure.tts.emotion_style).
    irodori_base_style: str = ""
    # Voice-design caption: a natural-language description of the target voice,
    # used by VoiceDesign checkpoints (Irodori-TTS-600M-v3-VoiceDesign) to
    # synthesize without a reference wav (no_ref). Passed to SamplingRequest.
    # Empty disables caption conditioning. This is the persona's "声の指示".
    irodori_caption: str = (
        "明るいが静かめの少女の声。少し高めで、親しみやすく、楽しそうに話してください。"
    )
    # Fixed sampling seed for Irodori so the voice (speaker timbre) stays
    # consistent across turns. VoiceDesign without a reference wav samples a new
    # speaker each call when this is None, so the voice drifts; a fixed seed pins
    # it (the caption still drives the style). Set None for random each turn.
    irodori_seed: int | None = 1234
    # Higher diffusion step count used only when *minting* a reference voice
    # (dashboard "ref生成", ADR-0013). Generation is one-off and quality matters
    # more than latency, so we use more steps than the per-turn synthesize path.
    irodori_generation_num_steps: int = 64


@lru_cache
def get_settings() -> AppSettings:
    """Return the cached application settings instance."""
    return AppSettings()
