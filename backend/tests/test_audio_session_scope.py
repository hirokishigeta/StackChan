"""Per-session audio codec isolation tests (Issue #27).

libopus encoders/decoders are stateful per stream. The container holds a single
shared instance, but each WS connection must receive its *own* enc/dec via
``for_session()`` so concurrent devices never interleave frames into the same
libopus state (which corrupts the audio). These tests verify:

- the stateless raw / fake codecs return ``self`` from ``for_session()`` (so the
  existing default wiring and tests keep sharing one harmless instance),
- the stateful Opus codecs return a *fresh* instance with an independent
  per-format cache (no native dep needed: a dummy encoder/decoder class is
  injected so libopus is never imported),
- the WS endpoint calls ``for_session()`` once per connection, so two
  connections end up with distinct enc/dec instances.
"""

from __future__ import annotations

from collections.abc import Callable

from app.application.ports.audio_decoder import AudioDecoder
from app.application.ports.audio_encoder import AudioEncoder
from app.di_container import container as container_module
from app.domain.speech.value_objects import AudioFormat
from app.infrastructure.audio.opus_audio_decoder import OpusAudioDecoder
from app.infrastructure.audio.opus_audio_encoder import OpusAudioEncoder
from app.infrastructure.audio.raw_pcm_audio_decoder import RawPcmAudioDecoder
from app.infrastructure.audio.raw_pcm_audio_encoder import RawPcmAudioEncoder
from fastapi.testclient import TestClient


def test_raw_codecs_share_one_instance_across_sessions() -> None:
    encoder = RawPcmAudioEncoder()
    decoder = RawPcmAudioDecoder()
    # Stateless: sharing is harmless, so for_session returns self.
    assert encoder.for_session() is encoder
    assert decoder.for_session() is decoder


def test_opus_encoder_for_session_returns_fresh_independent_instance() -> None:
    base = OpusAudioEncoder()
    a = base.for_session()
    b = base.for_session()
    assert a is not base
    assert a is not b
    # Independent per-format caches: a frame encoded on one session must not
    # land in another session's libopus encoder state.
    assert a._encoders is not b._encoders  # noqa: SLF001 - white-box regression


def test_opus_decoder_for_session_returns_fresh_independent_instance() -> None:
    base = OpusAudioDecoder()
    a = base.for_session()
    b = base.for_session()
    assert a is not base
    assert a is not b
    assert a._decoders is not b._decoders  # noqa: SLF001 - white-box regression


class _FakeNativeEncoder:
    """Stand-in for opuslib.Encoder: records frames so cross-session leakage
    would be observable, without importing libopus."""

    def __init__(self, *_args: object) -> None:
        self.seen: list[bytes] = []

    def encode(self, chunk: bytes, _samples: int) -> bytes:
        self.seen.append(chunk)
        return b"OPUS" + bytes([len(self.seen)])


def test_opus_encoder_isolated_state_per_session() -> None:
    """Two session encoders must build *separate* native encoders, so frames
    from one stream never reach the other's libopus state."""
    base = OpusAudioEncoder()
    base._encoder_cls = _FakeNativeEncoder  # noqa: SLF001 - bypass libopus import
    base._application = object()  # noqa: SLF001

    enc_a = base.for_session()
    enc_b = base.for_session()
    fmt = AudioFormat(codec="opus", sample_rate=24000, channels=1, frame_duration_ms=60)

    enc_a.encode(pcm=b"\x01\x02" * 1440, audio_format=fmt)
    enc_b.encode(pcm=b"\x03\x04" * 1440, audio_format=fmt)

    native_a = enc_a._encoders[(24000, 1)]  # noqa: SLF001
    native_b = enc_b._encoders[(24000, 1)]  # noqa: SLF001
    assert native_a is not native_b
    assert native_a.seen != native_b.seen


class _CountingEncoder(AudioEncoder):
    """An encoder that hands out a distinct instance per for_session() call."""

    def __init__(self, registry: list[AudioEncoder]) -> None:
        self._registry = registry

    def for_session(self) -> AudioEncoder:
        child = _CountingEncoder(self._registry)
        self._registry.append(child)
        return child

    def encode(self, *, pcm: bytes, audio_format: AudioFormat) -> list[bytes]:
        return [pcm] if pcm else []


class _CountingDecoder(AudioDecoder):
    def __init__(self, registry: list[AudioDecoder]) -> None:
        self._registry = registry

    def for_session(self) -> AudioDecoder:
        child = _CountingDecoder(self._registry)
        self._registry.append(child)
        return child

    def decode(self, *, payload: bytes, audio_format: AudioFormat) -> bytes:
        return payload


_HELLO = {
    "type": "hello",
    "version": 0,
    "transport": "websocket",
    "audio_params": {"format": "opus", "sample_rate": 16000, "channels": 1, "frame_duration": 60},
}


def test_ws_endpoint_creates_a_session_scoped_codec_per_connection(
    audio_ws_client_factory: Callable[..., TestClient],
) -> None:
    enc_instances: list[AudioEncoder] = []
    dec_instances: list[AudioDecoder] = []
    base_encoder = _CountingEncoder(enc_instances)
    base_decoder = _CountingDecoder(dec_instances)
    client = audio_ws_client_factory(
        audio_encoder=base_encoder,
        audio_decoder=base_decoder,
    )

    with client.websocket_connect("/api/bot/cores3-001/audio") as ws:
        ws.send_json(_HELLO)
        ws.receive_json()
    with client.websocket_connect("/api/bot/cores3-002/audio") as ws:
        ws.send_json(_HELLO)
        ws.receive_json()

    # One fresh instance per connection, and they are distinct from each other
    # and from the shared container instance.
    assert len(enc_instances) == 2
    assert len(dec_instances) == 2
    assert enc_instances[0] is not enc_instances[1]
    assert dec_instances[0] is not dec_instances[1]
    assert base_encoder not in enc_instances
    assert base_decoder not in dec_instances


def test_container_still_holds_shared_singletons(tmp_path: object) -> None:
    """The container keeps singletons (factories); session scoping happens at
    the WS edge. Accessing the property twice returns the same object."""
    from app.config.settings import AppSettings

    container = container_module.Container(
        AppSettings(database_url=f"sqlite:///{tmp_path}/c.db")  # type: ignore[str-bytes-safe]
    )
    assert container.audio_encoder is container.audio_encoder
    assert container.audio_decoder is container.audio_decoder
