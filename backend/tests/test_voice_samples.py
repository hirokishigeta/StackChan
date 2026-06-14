"""Voice-sample repository + API tests (ADR-0012).

Covers the filesystem repository (lists / resolves / labels / traversal guard)
and the HTTP endpoints (list, audio preview 200/404, traversal blocked). No
heavy deps: a wav here is just a few bytes on disk.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

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
