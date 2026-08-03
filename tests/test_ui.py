"""Testes dos controles de seleção e exibição das fontes de áudio."""

from __future__ import annotations

import io

import pytest
from rich.console import Console

from ai_audio_capture import ui


@pytest.mark.parametrize(
    ("choice", "expected"),
    [
        (1, (True, True)),
        (2, (True, False)),
        (3, (False, True)),
    ],
)
def test_prompt_capture_sources_maps_all_modes(
    monkeypatch: pytest.MonkeyPatch,
    choice: int,
    expected: tuple[bool, bool],
) -> None:
    monkeypatch.setattr(ui.IntPrompt, "ask", lambda *_args, **_kwargs: choice)

    assert ui.prompt_capture_sources() == expected


@pytest.mark.parametrize(
    ("capture_mic", "capture_pc", "visible", "hidden"),
    [
        (True, True, ("Microfone", "Áudio PC"), ()),
        (True, False, ("Microfone",), ("Áudio PC",)),
        (False, True, ("Áudio PC",), ("Microfone",)),
    ],
)
def test_dashboard_only_renders_active_source_meters(
    capture_mic: bool,
    capture_pc: bool,
    visible: tuple[str, ...],
    hidden: tuple[str, ...],
) -> None:
    dashboard = ui.RecordingDashboard(
        capture_mic=capture_mic,
        capture_pc=capture_pc,
    )
    panel = dashboard._render(
        paused=False,
        elapsed=0.0,
        mic_level=0.1,
        pc_level=0.2,
    )
    output = io.StringIO()
    console = Console(file=output, force_terminal=False, width=100)
    console.print(panel)
    rendered = output.getvalue()

    for label in visible:
        assert label in rendered
    for label in hidden:
        assert label not in rendered
