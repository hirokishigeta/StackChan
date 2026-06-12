"""Application configuration.

Values come from environment variables (prefix ``STACKCHAN_``) or defaults.
This module is referenceable from any layer (see CLAUDE.md dependency rules).
No hard-coded URLs / model names live outside of this module.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    """Runtime settings, overridable via environment variables.

    Example: ``STACKCHAN_DATABASE_URL=sqlite:///./prod.db``.
    """

    model_config = SettingsConfigDict(env_prefix="STACKCHAN_", env_file=".env", extra="ignore")

    app_name: str = "StackChan Backend"
    # SQLite by default; private-network local AI backend (design-spec §10).
    database_url: str = "sqlite:///./stackchan.db"

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

    # Downlink (server -> device) audio_params returned in the server hello.
    # These values are negotiated so firmware (#5) can rely on them; the
    # downlink TTS audio path (#7-b) resamples/encodes to these.
    downlink_sample_rate: int = 24000
    downlink_channels: int = 1
    downlink_frame_duration_ms: int = 60

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

    # TTS (downlink speech synthesis) provider, resolved via a registry. Default
    # is "dummy" so the process / make check run without heavy deps or models;
    # set "irodori" in deployment (ADR-0006). The WS loop falls back to a
    # text-only turn if synthesis is unavailable (design-spec §13).
    default_tts_provider: str = "dummy"

    # Irodori-TTS (ADR-0006). Heavy deps (PyTorch / HF checkpoint) are optional
    # and lazy-loaded; paths/device come from here (no hard-coded paths,
    # CLAUDE.md). Empty by default: IrodoriTtsSynthesizer raises a clear error
    # if used without these set. Irodori emits 48 kHz audio.
    irodori_model_path: str = ""
    irodori_reference_wav_path: str = ""
    irodori_device: str = "cpu"
    irodori_sample_rate: int = 48000


@lru_cache
def get_settings() -> AppSettings:
    """Return the cached application settings instance."""
    return AppSettings()
