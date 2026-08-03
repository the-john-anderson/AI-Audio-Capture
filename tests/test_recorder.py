"""Testes do orquestrador multi-thread (com ``soundcard`` simulado).

Evita ``sleep``-then-assert: aguarda condições reais com prazo limite e
finaliza via ``stop()``, que faz ``join`` de todas as threads — tornando as
asserções livres de corrida.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from ai_audio_capture.config import AudioConfig, RecordingConfig
from ai_audio_capture.recorder import AudioRecorder
from tests.fakes import FakeMic

_DEADLINE = 5.0


def _wait_until(predicate, timeout: float = _DEADLINE) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def _make_recorder(
    tmp_path: Path,
    *,
    capture_mic: bool = True,
    capture_pc: bool,
    max_bytes: int = 0,
) -> AudioRecorder:
    config = RecordingConfig(
        capture_mic=capture_mic,
        capture_pc=capture_pc,
        output_dir=tmp_path,
        file_name="session.wav",
        max_bytes=max_bytes,
    )
    mic = FakeMic() if capture_mic else None
    return AudioRecorder(mic, config, AudioConfig())


@pytest.mark.parametrize(
    ("capture_mic", "capture_pc", "expected_channels"),
    [
        (True, True, 2),
        (True, False, 1),
        (False, True, 1),
    ],
)
def test_pipeline_writes_each_capture_mode(
    tmp_path: Path,
    patch_loopback: None,
    capture_mic: bool,
    capture_pc: bool,
    expected_channels: int,
) -> None:
    rec = _make_recorder(
        tmp_path,
        capture_mic=capture_mic,
        capture_pc=capture_pc,
    )
    rec.start()
    assert _wait_until(lambda: rec.generated_files and rec.generated_files[0].exists())
    if capture_mic:
        assert _wait_until(lambda: rec.mic_level > 0)
    if capture_pc:
        assert _wait_until(lambda: rec.pc_level > 0)
    rec.stop()

    assert rec.error is None
    data, sample_rate = sf.read(str(rec.generated_files[0]), always_2d=True)
    assert sample_rate == 16_000
    assert data.shape[1] == expected_channels
    assert data.shape[0] > 0


def test_mic_only_never_opens_loopback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden_loopback() -> str:
        raise AssertionError("loopback não deve ser consultado")

    monkeypatch.setattr("ai_audio_capture.devices.default_speaker_id", forbidden_loopback)
    rec = _make_recorder(tmp_path, capture_pc=False)
    rec.start()
    assert _wait_until(lambda: rec.mic_level > 0)
    rec.stop()

    assert rec.error is None


def test_pc_only_never_opens_microphone(tmp_path: Path, patch_loopback: None) -> None:
    rec = _make_recorder(tmp_path, capture_mic=False, capture_pc=True)
    assert rec._mic is None

    rec.start()
    assert _wait_until(lambda: rec.pc_level > 0)
    rec.stop()

    assert rec.error is None


def test_loopback_read_failure_reopens_same_device(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rec = _make_recorder(tmp_path, capture_mic=False, capture_pc=True)
    opened: list[object] = []

    class FailingStream:
        def record(self, numframes: int) -> np.ndarray:
            raise OSError("falha transitória")

        def __exit__(self, *exc: object) -> bool:
            return False

    class RecoveredStream:
        def record(self, numframes: int) -> np.ndarray:
            rec._capture_stop_event.set()
            return np.full((numframes, 1), 0.2, np.float32)

        def __exit__(self, *exc: object) -> bool:
            return False

    streams = [FailingStream(), RecoveredStream()]

    def open_loopback(_speaker_id: object) -> object:
        index = min(len(opened), len(streams) - 1)
        stream = streams[index]
        opened.append(stream)
        return stream

    monkeypatch.setattr("ai_audio_capture.devices.default_speaker_id", lambda: "speaker-id")
    monkeypatch.setattr(rec, "_open_loopback", open_loopback)

    worker = threading.Thread(target=rec._pc_worker, name="loopback-reconnect-test")
    worker.start()
    reopened = _wait_until(lambda: len(opened) >= 2, timeout=1.0)
    rec._capture_stop_event.set()
    worker.join(timeout=_DEADLINE)

    assert not worker.is_alive()
    assert reopened, "o stream que falhou não foi reaberto"
    assert rec.error is None


def test_toggle_pause_reports_state(tmp_path: Path) -> None:
    rec = _make_recorder(tmp_path, capture_pc=False)
    assert rec.is_paused() is False
    assert rec.toggle_pause() is True
    assert rec.is_paused() is True
    assert rec.toggle_pause() is False
    assert rec.is_paused() is False


def test_stop_is_idempotent(tmp_path: Path) -> None:
    rec = _make_recorder(tmp_path, capture_pc=False)
    rec.start()
    _wait_until(lambda: bool(rec.generated_files))
    rec.stop()
    rec.stop()  # não deve lançar
    assert rec.is_running() is False


def test_start_rejects_duplicate_call(tmp_path: Path) -> None:
    rec = _make_recorder(tmp_path, capture_pc=False)
    assert rec.is_running() is False

    rec.start()
    try:
        with pytest.raises(RuntimeError, match="inici|start|uso"):
            rec.start()
    finally:
        rec.stop()


def test_recorder_cannot_restart_after_stop(tmp_path: Path) -> None:
    rec = _make_recorder(tmp_path, capture_pc=False)
    rec.start()
    rec.stop()

    with pytest.raises(RuntimeError, match="inici|start|uso"):
        rec.start()


def test_stop_drains_captured_chunks_before_writer_closes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rec = _make_recorder(tmp_path, capture_pc=False)
    chunks = [np.full((32, 1), value, np.float32) for value in (0.1, 0.2, 0.3, 0.4)]
    for chunk in chunks:
        rec._mic_queue.put(chunk)

    # O worker de captura não produz mais dados: os blocos acima representam
    # tudo que já saiu do hardware quando a parada foi solicitada.
    monkeypatch.setattr(rec, "_mic_worker", lambda: None)

    entered_processor = threading.Event()
    release_processor = threading.Event()
    original_process = rec._processor.process_chunk

    def delayed_process(audio_mic: np.ndarray | None, audio_pc: np.ndarray | None):
        entered_processor.set()
        assert release_processor.wait(_DEADLINE)
        return original_process(audio_mic, audio_pc)

    monkeypatch.setattr(rec._processor, "process_chunk", delayed_process)

    rec.start()
    assert entered_processor.wait(_DEADLINE)

    stopper = threading.Thread(target=rec.stop, name="stopper-test")
    stopper.start()
    assert _wait_until(rec._capture_stop_event.is_set)
    release_processor.set()
    stopper.join(timeout=_DEADLINE)
    assert not stopper.is_alive()

    data, _ = sf.read(str(rec.generated_files[0]), always_2d=True)
    assert data.shape == (sum(len(chunk) for chunk in chunks), 1)


def test_size_splitting(tmp_path: Path) -> None:
    """Alimenta o writer diretamente para forçar a divisão por tamanho."""
    rec = _make_recorder(tmp_path, capture_pc=False, max_bytes=8_000)

    writer = threading.Thread(target=rec._writer_worker, name="writer-test")
    writer.start()

    chunk = np.zeros((1024, 1), np.float32)  # 1024*1*2 = 2048 bytes/chunk
    for _ in range(8):
        rec._disk_queue.put(chunk)  # put bloqueante → contagem determinística

    assert _wait_until(lambda: rec._disk_queue.empty())
    rec._processing_done_event.set()
    writer.join(timeout=_DEADLINE)
    assert not writer.is_alive()

    parts = rec.generated_files
    assert len(parts) > 1
    for part in parts:
        assert part.name.startswith("session_parte")
        assert part.exists()
        data, _ = sf.read(str(part))
        # Cada parte respeita o limite (com tolerância de 1 chunk).
        assert data.shape[0] * 2 <= 8_000 + 2_048


def test_no_empty_leading_part_when_chunk_exceeds_limit(tmp_path: Path) -> None:
    """Um chunk maior que o limite não deve gerar uma parte vazia inicial."""
    rec = _make_recorder(tmp_path, capture_pc=False, max_bytes=1_000)  # < 2048 B/chunk
    writer = threading.Thread(target=rec._writer_worker, name="writer-test")
    writer.start()
    for _ in range(3):
        rec._disk_queue.put(np.zeros((1024, 1), np.float32))
    assert _wait_until(lambda: rec._disk_queue.empty())
    rec._processing_done_event.set()
    writer.join(timeout=_DEADLINE)

    parts = rec.generated_files
    assert len(parts) == 3  # uma por chunk, nenhuma vazia
    for part in parts:
        data, _ = sf.read(str(part))
        assert data.shape[0] == 1024  # nenhuma parte vazia


def test_no_split_without_limit(tmp_path: Path) -> None:
    rec = _make_recorder(tmp_path, capture_pc=False, max_bytes=0)
    writer = threading.Thread(target=rec._writer_worker, name="writer-test")
    writer.start()
    for _ in range(3):
        rec._disk_queue.put(np.zeros((1024, 1), np.float32))
    assert _wait_until(lambda: rec._disk_queue.empty())
    rec._processing_done_event.set()
    writer.join(timeout=_DEADLINE)

    assert rec.generated_files == [tmp_path / "session.wav"]
    data, _ = sf.read(str(rec.generated_files[0]))
    assert data.shape[0] == 3 * 1024
