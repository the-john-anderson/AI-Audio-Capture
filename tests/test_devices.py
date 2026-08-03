"""Testes do isolamento da biblioteca ``soundcard``."""

from __future__ import annotations

import pytest

from ai_audio_capture import devices


def test_device_error_when_soundcard_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(devices, "_sc", None)
    with pytest.raises(devices.DeviceError):
        devices.list_microphones()
    with pytest.raises(devices.DeviceError):
        devices.default_microphone()


def test_list_microphones_delegates_to_soundcard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = [object(), object()]
    fake_sc = type("SC", (), {"all_microphones": staticmethod(lambda: sentinel)})
    monkeypatch.setattr(devices, "_sc", fake_sc)
    assert devices.list_microphones() == sentinel


def test_loopback_for_speaker_passes_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_get_microphone(id: object, include_loopback: bool = False) -> str:
        captured["id"] = id
        captured["include_loopback"] = include_loopback
        return "loopback-mic"

    fake_sc = type("SC", (), {"get_microphone": staticmethod(fake_get_microphone)})
    monkeypatch.setattr(devices, "_sc", fake_sc)

    result = devices.loopback_for_speaker("spk-1")
    assert result == "loopback-mic"
    assert captured == {"id": "spk-1", "include_loopback": True}
