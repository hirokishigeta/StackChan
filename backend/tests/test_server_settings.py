"""Server-settings API + runtime voice config tests (ADR-0009).

Covers the GET/PUT round-trip, the default fallback (env defaults when no
override is persisted), validation 422 on an unknown provider, and the
synthesizer reading the runtime caption per-call. Heavy deps are mocked: the
synthesizer test injects a fake runtime so torch is never imported (CLAUDE.md).
"""

from __future__ import annotations

from typing import Any

from app.application.ports.voice_sample_repository import VoiceSampleRepository
from app.application.use_cases.manage_server_settings import ManageServerSettingsUseCase
from app.config.settings import AppSettings
from app.domain.settings.value_objects import ServerVoiceSettings
from app.domain.speech.value_objects import VoiceSample
from app.infrastructure.persistence.sqlite_server_settings_repository import (
    SqliteServerSettingsRepository,
)
from app.infrastructure.tts.irodori_tts_synthesizer import IrodoriTtsSynthesizer
from app.interfaces.dashboard import routes as dashboard_routes
from fastapi.testclient import TestClient


def test_get_server_settings_default_fallback(client: TestClient) -> None:
    """With no persisted override, GET returns the AppSettings/env defaults."""
    defaults = AppSettings(_env_file=None)
    resp = client.get("/api/server-settings")
    assert resp.status_code == 200
    body = resp.json()
    assert body["tts_provider"] == defaults.default_tts_provider
    assert body["irodori_caption"] == defaults.irodori_caption
    assert body["irodori_base_style"] == defaults.irodori_base_style


def test_put_then_get_round_trip(client: TestClient) -> None:
    """PUT persists the override; a subsequent GET returns it."""
    payload = {
        "tts_provider": "irodori",
        "irodori_caption": "落ち着いた青年の声。",
        "irodori_base_style": "😊",
    }
    expected = {**payload, "voice_sample_id": None}
    put = client.put("/api/server-settings", json=payload)
    assert put.status_code == 200
    assert put.json() == expected

    got = client.get("/api/server-settings")
    assert got.status_code == 200
    assert got.json() == expected


def test_put_unknown_provider_is_422(client: TestClient) -> None:
    resp = client.put(
        "/api/server-settings",
        json={
            "tts_provider": "nope",
            "irodori_caption": "x",
            "irodori_base_style": "",
        },
    )
    assert resp.status_code == 422


def test_put_missing_field_is_422(client: TestClient) -> None:
    resp = client.put("/api/server-settings", json={"tts_provider": "dummy"})
    assert resp.status_code == 422


class _FakeVoiceSampleRepository(VoiceSampleRepository):
    """In-memory VoiceSampleRepository for use-case tests (no filesystem)."""

    def __init__(self, samples: dict[str, str] | None = None) -> None:
        # id -> wav path
        self._samples = samples or {}

    def list_samples(self) -> list[VoiceSample]:
        return [VoiceSample(id=sid, label=sid) for sid in sorted(self._samples)]

    def resolve_wav_path(self, sample_id: str) -> str | None:
        return self._samples.get(sample_id)

    def save(
        self,
        *,
        sample_id: str,
        pcm: bytes,
        sample_rate: int,
        label: str | None = None,
        caption: str | None = None,
    ) -> VoiceSample:
        self._samples[sample_id] = f"/voices/{sample_id}.wav"
        return VoiceSample(id=sample_id, label=label or sample_id)


def test_repository_default_then_override(tmp_path: object) -> None:
    """The use case returns env defaults until an override is saved."""
    db = f"sqlite:///{tmp_path}/srv.db"  # type: ignore[str-bytes-safe]
    settings = AppSettings(_env_file=None, irodori_caption="env-caption")
    repo = SqliteServerSettingsRepository(db)
    use_case = ManageServerSettingsUseCase(repo, settings, _FakeVoiceSampleRepository())

    assert use_case.current_voice().irodori_caption == "env-caption"

    use_case.update_voice(
        ServerVoiceSettings(
            tts_provider="irodori",
            irodori_caption="override-caption",
            irodori_base_style="✨",
        )
    )
    effective = use_case.current_voice()
    assert effective.irodori_caption == "override-caption"
    assert effective.tts_provider == "irodori"
    assert effective.irodori_base_style == "✨"


class _FakeRuntime:
    """Captures the SamplingRequest passed to synthesize (no torch)."""

    def __init__(self) -> None:
        self.last_request: Any | None = None

    def synthesize(self, request: Any) -> Any:
        self.last_request = request

        class _Result:
            audio = [[0.0, 0.0, 0.0]]
            sample_rate = 48000

        return _Result()


class _FakeRequest:
    """Stand-in for irodori_tts SamplingRequest; records the caption."""

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs


def test_synthesizer_reads_runtime_caption(tmp_path: object) -> None:
    """A caption changed at runtime is used on the next synthesize (no restart)."""
    db = f"sqlite:///{tmp_path}/srv2.db"  # type: ignore[str-bytes-safe]
    settings = AppSettings(_env_file=None, irodori_caption="default-caption")
    repo = SqliteServerSettingsRepository(db)
    use_case = ManageServerSettingsUseCase(repo, settings, _FakeVoiceSampleRepository())

    synth = IrodoriTtsSynthesizer(settings, use_case)
    # Inject the fake runtime so the optional heavy deps are never imported.
    fake = _FakeRuntime()
    synth._runtime = fake  # noqa: SLF001 - test-only injection
    synth._request_cls = _FakeRequest  # noqa: SLF001

    synth.synthesize(text="hello", emotion="neutral")
    assert fake.last_request.kwargs["caption"] == "default-caption"

    # Change the caption via the dashboard path; next synthesize must pick it up.
    use_case.update_voice(
        ServerVoiceSettings(
            tts_provider="irodori",
            irodori_caption="new-runtime-caption",
            irodori_base_style="",
        )
    )
    synth.synthesize(text="hello again", emotion="neutral")
    assert fake.last_request.kwargs["caption"] == "new-runtime-caption"


def test_update_voice_unknown_sample_raises(tmp_path: object) -> None:
    """Selecting a non-existent sample id is rejected at the use-case boundary."""
    db = f"sqlite:///{tmp_path}/srv3.db"  # type: ignore[str-bytes-safe]
    settings = AppSettings(_env_file=None)
    repo = SqliteServerSettingsRepository(db)
    samples = _FakeVoiceSampleRepository({"alice": "/tmp/alice.wav"})
    use_case = ManageServerSettingsUseCase(repo, settings, samples)

    from app.application.use_cases.manage_server_settings import UnknownVoiceSampleError

    try:
        use_case.update_voice(
            ServerVoiceSettings(
                tts_provider="irodori",
                irodori_caption="",
                irodori_base_style="",
                voice_sample_id="ghost",
            )
        )
        raise AssertionError("expected UnknownVoiceSampleError")
    except UnknownVoiceSampleError:
        pass


def test_selected_reference_wav_resolves(tmp_path: object) -> None:
    """selected_reference_wav resolves the chosen sample's wav path; None if unset."""
    db = f"sqlite:///{tmp_path}/srv4.db"  # type: ignore[str-bytes-safe]
    settings = AppSettings(_env_file=None)
    repo = SqliteServerSettingsRepository(db)
    samples = _FakeVoiceSampleRepository({"alice": "/voices/alice.wav"})
    use_case = ManageServerSettingsUseCase(repo, settings, samples)

    assert use_case.selected_reference_wav() is None

    use_case.update_voice(
        ServerVoiceSettings(
            tts_provider="irodori",
            irodori_caption="",
            irodori_base_style="",
            voice_sample_id="alice",
        )
    )
    assert use_case.selected_reference_wav() == "/voices/alice.wav"


def test_synthesizer_uses_selected_sample_as_ref(tmp_path: object) -> None:
    """The selected sample's wav is passed as ref_wav (no_ref False)."""
    db = f"sqlite:///{tmp_path}/srv5.db"  # type: ignore[str-bytes-safe]
    settings = AppSettings(_env_file=None)
    repo = SqliteServerSettingsRepository(db)
    samples = _FakeVoiceSampleRepository({"alice": "/voices/alice.wav"})
    use_case = ManageServerSettingsUseCase(repo, settings, samples)
    use_case.update_voice(
        ServerVoiceSettings(
            tts_provider="irodori",
            irodori_caption="",
            irodori_base_style="",
            voice_sample_id="alice",
        )
    )

    synth = IrodoriTtsSynthesizer(settings, use_case)
    fake = _FakeRuntime()
    synth._runtime = fake  # noqa: SLF001
    synth._request_cls = _FakeRequest  # noqa: SLF001

    synth.synthesize(text="hi", emotion="neutral")
    assert fake.last_request.kwargs["ref_wav"] == "/voices/alice.wav"
    assert fake.last_request.kwargs["no_ref"] is False


def test_server_settings_round_trip_includes_sample(client: TestClient) -> None:
    """voice_sample_id is absent by default and round-trips when null."""
    got = client.get("/api/server-settings")
    assert got.status_code == 200
    assert got.json()["voice_sample_id"] is None

    payload = {
        "tts_provider": "irodori",
        "irodori_caption": "x",
        "irodori_base_style": "",
        "voice_sample_id": None,
    }
    put = client.put("/api/server-settings", json=payload)
    assert put.status_code == 200
    assert put.json()["voice_sample_id"] is None


def test_put_unknown_sample_is_422(client: TestClient) -> None:
    resp = client.put(
        "/api/server-settings",
        json={
            "tts_provider": "irodori",
            "irodori_caption": "x",
            "irodori_base_style": "",
            "voice_sample_id": "does-not-exist",
        },
    )
    assert resp.status_code == 422


def test_dashboard_serves_html(client: TestClient) -> None:
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    assert "StackChan" in resp.text
    assert "__DEFAULT_DEVICE_ID__" in resp.text


def test_dashboard_render_injects_devices() -> None:
    html = dashboard_routes._render(["dev-a", "dev-b"], "dev-a")  # noqa: SLF001
    assert '"dev-a"' in html
    assert '"dev-b"' in html
    assert "window.__KNOWN_DEVICES__" in html


def test_dashboard_has_wakeword_tab() -> None:
    html = dashboard_routes._render([], "dev-a")  # noqa: SLF001
    assert 'data-target="wakeword"' in html
    assert 'data-panel="wakeword"' in html
    assert "ウェイクワード" in html


def test_dashboard_has_voice_sample_picker() -> None:
    html = dashboard_routes._render([], "dev-a")  # noqa: SLF001
    assert 'id="voice-sample-list"' in html
    assert "/api/voice-samples" in html
    assert "声サンプル" in html
