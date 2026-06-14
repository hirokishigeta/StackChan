"""Filesystem-backed VoiceSampleRepository (ADR-0012).

Each ``.wav`` in ``STACKCHAN_VOICE_SAMPLES_DIR`` is one selectable reference
voice; the sample id is the filename stem. A human label is the stem by
default, optionally overridden by a sidecar ``<stem>.txt`` (single line) or a
``samples.json`` mapping ``id -> label`` (or ``id -> {"label": ...}``) in the
same directory. The metadata files are optional — missing means label == stem.

Path resolution is hardened against traversal: a resolved wav must live directly
inside the (resolved) samples dir, so a crafted id like ``../secret`` resolves
to ``None`` rather than escaping the directory (the API serves the bytes).
"""

from __future__ import annotations

import json
from pathlib import Path

from app.application.ports.voice_sample_repository import VoiceSampleRepository
from app.domain.speech.value_objects import VoiceSample

_METADATA_FILENAME = "samples.json"


class FilesystemVoiceSampleRepository(VoiceSampleRepository):
    """Lists / resolves voice samples from a directory of wav files."""

    def __init__(self, samples_dir: str) -> None:
        # ``expanduser`` so "~/.stackchan/voice_samples" works (no hard-coded
        # paths; the value comes from AppSettings). The dir need not exist yet:
        # the wavs are generated separately on the GPU host.
        self._dir = Path(samples_dir).expanduser()

    def _resolved_dir(self) -> Path:
        try:
            return self._dir.resolve()
        except OSError:  # pragma: no cover - defensive
            return self._dir

    def list_samples(self) -> list[VoiceSample]:
        directory = self._dir
        if not directory.is_dir():
            return []
        labels = self._load_labels(directory)
        samples = [
            VoiceSample(id=wav.stem, label=labels.get(wav.stem, wav.stem))
            for wav in sorted(directory.glob("*.wav"))
            if wav.is_file()
        ]
        return samples

    def resolve_wav_path(self, sample_id: str) -> str | None:
        # Reject empty / path-bearing ids outright before touching the FS.
        if not sample_id or "/" in sample_id or "\\" in sample_id or sample_id in (".", ".."):
            return None
        base = self._resolved_dir()
        candidate = (self._dir / f"{sample_id}.wav").resolve()
        # The resolved candidate must be a direct child of the samples dir.
        if candidate.parent != base:
            return None
        if not candidate.is_file():
            return None
        return str(candidate)

    @staticmethod
    def _load_labels(directory: Path) -> dict[str, str]:
        """Build id -> label from samples.json and per-sample sidecar txt files.

        samples.json takes precedence; a ``<stem>.txt`` sidecar fills in any id
        not covered by it. Malformed metadata is ignored (labels fall back to
        the stem) so a bad file never breaks listing.
        """
        labels: dict[str, str] = {}
        for sidecar in directory.glob("*.txt"):
            try:
                text = sidecar.read_text(encoding="utf-8").strip()
            except OSError:  # pragma: no cover - defensive
                continue
            if text:
                labels[sidecar.stem] = text.splitlines()[0].strip()
        manifest = directory / _METADATA_FILENAME
        if manifest.is_file():
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = None
            if isinstance(data, dict):
                for key, value in data.items():
                    label = FilesystemVoiceSampleRepository._coerce_label(value)
                    if label:
                        labels[str(key)] = label
        return labels

    @staticmethod
    def _coerce_label(value: object) -> str | None:
        if isinstance(value, str):
            return value.strip() or None
        if isinstance(value, dict):
            for field in ("label", "caption"):
                field_value = value.get(field)
                if isinstance(field_value, str) and field_value.strip():
                    return field_value.strip()
        return None
