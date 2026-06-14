"""Voice-sample repository + API tests (ADR-0012).

Covers the filesystem repository (lists / resolves / labels / traversal guard)
and the HTTP endpoints (list, audio preview 200/404, traversal blocked). No
heavy deps: a wav here is just a few bytes on disk.
"""

from __future__ import annotations

import json
import struct
import wave
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from app.application.ports.speech_synthesizer import SpeechSynthesisError
from app.application.ports.voice_sample_repository import (
    DuplicateSampleError,
    InvalidSampleIdError,
)
from app.domain.speech.value_objects import SynthesizedAudio
from app.infrastructure.persistence.filesystem_voice_sample_repository import (
    FilesystemVoiceSampleRepository,
)
from fastapi.testclient import TestClient

from .conftest import _client_with_container, _make_container  # type: ignore[attr-defined]

# Minimal valid-ish RIFF/WAVE header + tiny payload; enough for FileResponse.
_WAV_BYTES = (
    b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00"
    b"\x40\x1f\x00\x00\x80>\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
)


def _write_wav(directory: Path, stem: str) -> Path:
    path = directory / f"{stem}.wav"
    path.write_bytes(_WAV_BYTES)
    return path


def test_repo_lists_empty_when_dir_missing(tmp_path: Path) -> None:
    repo = FilesystemVoiceSampleRepository(str(tmp_path / "nope"))
    assert repo.list_samples() == []


def test_repo_lists_and_resolves(tmp_path: Path) -> None:
    _write_wav(tmp_path, "bob")
    _write_wav(tmp_path, "alice")
    repo = FilesystemVoiceSampleRepository(str(tmp_path))

    samples = repo.list_samples()
    ids = [s.id for s in samples]
    assert ids == ["alice", "bob"]  # sorted
    assert all(s.label == s.id for s in samples)  # label defaults to stem

    resolved = repo.resolve_wav_path("alice")
    assert resolved is not None
    assert Path(resolved).name == "alice.wav"
    assert repo.resolve_wav_path("ghost") is None


def test_repo_label_from_sidecar_and_manifest(tmp_path: Path) -> None:
    _write_wav(tmp_path, "alice")
    _write_wav(tmp_path, "bob")
    (tmp_path / "alice.txt").write_text("アリスの声\n2行目", encoding="utf-8")
    (tmp_path / "samples.json").write_text(
        json.dumps({"bob": {"label": "ボブ"}}, ensure_ascii=False), encoding="utf-8"
    )
    repo = FilesystemVoiceSampleRepository(str(tmp_path))

    labels = {s.id: s.label for s in repo.list_samples()}
    assert labels["alice"] == "アリスの声"  # first line of sidecar
    assert labels["bob"] == "ボブ"  # manifest entry


def test_repo_blocks_traversal(tmp_path: Path) -> None:
    secret = tmp_path / "secret.wav"
    secret.write_bytes(_WAV_BYTES)
    samples_dir = tmp_path / "samples"
    samples_dir.mkdir()
    repo = FilesystemVoiceSampleRepository(str(samples_dir))

    assert repo.resolve_wav_path("../secret") is None
    assert repo.resolve_wav_path("..") is None
    assert repo.resolve_wav_path("") is None


# ---- repository.save (ADR-0013) ----


def test_repo_save_round_trips(tmp_path: Path) -> None:
    samples_dir = tmp_path / "voices"
    repo = FilesystemVoiceSampleRepository(str(samples_dir))  # dir does not exist yet
    pcm = struct.pack("<4h", 100, -100, 200, -200)

    sample = repo.save(
        sample_id="cute-01", pcm=pcm, sample_rate=24000, label="かわいい声", caption="明るい少女"
    )
    assert sample.id == "cute-01"
    assert sample.label == "かわいい声"

    # The wav exists and is readable as a 1ch/16-bit/24k wave with our frames.
    wav_path = repo.resolve_wav_path("cute-01")
    assert wav_path is not None
    with wave.open(wav_path, "rb") as wav:
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.getframerate() == 24000
        assert wav.readframes(wav.getnframes()) == pcm

    # It is now listable with the recorded label (samples.json).
    labels = {s.id: s.label for s in repo.list_samples()}
    assert labels["cute-01"] == "かわいい声"


def test_repo_save_merges_metadata_without_clobbering(tmp_path: Path) -> None:
    samples_dir = tmp_path / "voices"
    samples_dir.mkdir()
    _write_wav(samples_dir, "existing")
    (samples_dir / "samples.json").write_text(
        json.dumps({"existing": {"label": "既存"}}, ensure_ascii=False), encoding="utf-8"
    )
    repo = FilesystemVoiceSampleRepository(str(samples_dir))
    repo.save(sample_id="new-one", pcm=b"\x00\x00", sample_rate=24000, label="新規")

    data = json.loads((samples_dir / "samples.json").read_text(encoding="utf-8"))
    assert data["existing"]["label"] == "既存"  # untouched
    assert data["new-one"]["label"] == "新規"


def test_repo_save_label_defaults_to_id(tmp_path: Path) -> None:
    repo = FilesystemVoiceSampleRepository(str(tmp_path / "voices"))
    sample = repo.save(sample_id="bare", pcm=b"\x00\x00", sample_rate=24000)
    assert sample.label == "bare"


def test_repo_save_rejects_bad_slug(tmp_path: Path) -> None:
    repo = FilesystemVoiceSampleRepository(str(tmp_path / "voices"))
    for bad in ("../escape", "with/slash", "with\\back", "", "空白あり 名前"):
        with pytest.raises(InvalidSampleIdError):
            repo.save(sample_id=bad, pcm=b"\x00\x00", sample_rate=24000)


def test_repo_save_rejects_duplicate(tmp_path: Path) -> None:
    repo = FilesystemVoiceSampleRepository(str(tmp_path / "voices"))
    repo.save(sample_id="dup", pcm=b"\x00\x00", sample_rate=24000)
    with pytest.raises(DuplicateSampleError):
        repo.save(sample_id="dup", pcm=b"\x00\x00", sample_rate=24000)


@contextmanager
def _client_with_samples_dir(tmp_path: Path, samples_dir: Path) -> Iterator[TestClient]:
    container = _make_container(
        tmp_path, settings_overrides={"voice_samples_dir": str(samples_dir)}
    )
    with _client_with_container(container) as client:
        yield client


def test_api_lists_samples(tmp_path: Path) -> None:
    samples_dir = tmp_path / "voices"
    samples_dir.mkdir()
    _write_wav(samples_dir, "alice")
    with _client_with_samples_dir(tmp_path, samples_dir) as client:
        resp = client.get("/api/voice-samples")
        assert resp.status_code == 200
        assert resp.json() == [{"id": "alice", "label": "alice"}]


def test_api_audio_200_and_404(tmp_path: Path) -> None:
    samples_dir = tmp_path / "voices"
    samples_dir.mkdir()
    _write_wav(samples_dir, "alice")
    with _client_with_samples_dir(tmp_path, samples_dir) as client:
        ok = client.get("/api/voice-samples/alice/audio")
        assert ok.status_code == 200
        assert ok.headers["content-type"] == "audio/wav"
        assert ok.content == _WAV_BYTES

        missing = client.get("/api/voice-samples/ghost/audio")
        assert missing.status_code == 404


def test_api_audio_blocks_traversal(tmp_path: Path) -> None:
    samples_dir = tmp_path / "voices"
    samples_dir.mkdir()
    _write_wav(samples_dir, "alice")
    # A wav outside the samples dir that a traversal could target.
    (tmp_path / "secret.wav").write_bytes(_WAV_BYTES)
    with _client_with_samples_dir(tmp_path, samples_dir) as client:
        resp = client.get("/api/voice-samples/..%2Fsecret/audio")
        assert resp.status_code == 404


# ---- POST /api/voice-samples (generation, ADR-0013) ----


class _FakeSynth:
    """A SpeechSynthesizer-like fake: generate_reference returns small PCM."""

    def __init__(self, *, raises: bool = False) -> None:
        self._raises = raises
        self.calls: list[dict[str, object]] = []

    def generate_reference(
        self, *, text: str, caption: str, seed: int | None = None
    ) -> SynthesizedAudio:
        self.calls.append({"text": text, "caption": caption, "seed": seed})
        if self._raises:
            raise SpeechSynthesisError("engine unavailable")
        return SynthesizedAudio(pcm=struct.pack("<2h", 123, -123), sample_rate=24000)


@contextmanager
def _client_with_synth(
    tmp_path: Path, samples_dir: Path, synth: _FakeSynth
) -> Iterator[TestClient]:
    container = _make_container(
        tmp_path,
        settings_overrides={"voice_samples_dir": str(samples_dir)},
        speech_synthesizer=synth,
    )
    with _client_with_container(container) as client:
        yield client


def test_api_post_creates_listable_sample(tmp_path: Path) -> None:
    samples_dir = tmp_path / "voices"
    synth = _FakeSynth()
    with _client_with_synth(tmp_path, samples_dir, synth) as client:
        resp = client.post(
            "/api/voice-samples",
            json={"id": "minted-01", "label": "ミント声", "caption": "明るい少女の声"},
        )
        assert resp.status_code == 201
        assert resp.json() == {"id": "minted-01", "label": "ミント声"}
        # generate_reference saw the caption (and the default example text).
        assert synth.calls[0]["caption"] == "明るい少女の声"
        assert synth.calls[0]["text"] == "こんにちは、今日はどんなお話をしましょうか？"

        listing = client.get("/api/voice-samples").json()
        assert {"id": "minted-01", "label": "ミント声"} in listing


def test_api_post_422_empty_caption(tmp_path: Path) -> None:
    samples_dir = tmp_path / "voices"
    with _client_with_synth(tmp_path, samples_dir, _FakeSynth()) as client:
        resp = client.post("/api/voice-samples", json={"id": "x", "caption": "   "})
        assert resp.status_code == 422


def test_api_post_422_bad_id(tmp_path: Path) -> None:
    samples_dir = tmp_path / "voices"
    with _client_with_synth(tmp_path, samples_dir, _FakeSynth()) as client:
        resp = client.post("/api/voice-samples", json={"id": "../escape", "caption": "声"})
        assert resp.status_code == 422


def test_api_post_409_duplicate(tmp_path: Path) -> None:
    samples_dir = tmp_path / "voices"
    samples_dir.mkdir()
    _write_wav(samples_dir, "taken")
    with _client_with_synth(tmp_path, samples_dir, _FakeSynth()) as client:
        resp = client.post("/api/voice-samples", json={"id": "taken", "caption": "声"})
        assert resp.status_code == 409


def test_api_post_503_when_synth_unavailable(tmp_path: Path) -> None:
    samples_dir = tmp_path / "voices"
    with _client_with_synth(tmp_path, samples_dir, _FakeSynth(raises=True)) as client:
        resp = client.post("/api/voice-samples", json={"id": "novoice", "caption": "声"})
        assert resp.status_code == 503
