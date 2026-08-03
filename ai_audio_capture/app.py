"""Fluxo principal da aplicação AI-Audio-Capture.

Orquestra a interação com o usuário (via :mod:`ui`), a captura (via
:mod:`recorder`) e o pós-processamento opcional (via :mod:`postprocess`),
mantendo a lógica de plataforma e de DSP isolada nos respectivos módulos.
"""

from __future__ import annotations

import time
from datetime import datetime
from logging import Logger
from pathlib import Path

from . import devices, keyboard, postprocess, ui
from .config import (
    AppSettings,
    PostProcessConfig,
    RecordingConfig,
    get_settings,
)
from .logging_setup import configure_logging
from .recorder import AudioRecorder
from .timing import ElapsedTimer

_POLL_INTERVAL = 0.05  # cadência de leitura de teclado (s)


def run() -> None:
    """Ponto de entrada interativo da aplicação."""
    settings = get_settings()
    log = configure_logging(settings.log_file, settings.log_level)
    log.info("=== Nova sessão de captura iniciada ===")

    try:
        _run_session(settings, log)
    except devices.DeviceError as exc:
        ui.print_error(str(exc))
        log.error("Erro de dispositivo: %s", exc)
        raise SystemExit(1) from exc
    except KeyboardInterrupt:
        ui.print_warning("Interrompido pelo usuário (Ctrl+C).")
        log.warning("Sessão interrompida via Ctrl+C antes de iniciar a gravação.")
    finally:
        log.info("=== Sessão encerrada ===")


def _run_session(settings: AppSettings, log: Logger) -> None:
    """Executa uma sessão completa de configuração, gravação e pós-processo."""
    ui.print_banner()

    capture_mic, capture_pc = ui.prompt_capture_sources()
    apply_ducking = capture_mic and capture_pc and postprocess.is_ducking_available()
    if capture_mic and capture_pc and not apply_ducking:
        ui.print_warning(
            "'scipy' não encontrado — redução de eco desativada (instale com: pip install scipy)."
        )

    apply_nr = capture_mic and postprocess.is_noise_reduction_available()
    if capture_mic and not apply_nr:
        ui.print_warning(
            "'noisereduce' não encontrado — limpeza de ruído desativada "
            "(instale com: pip install noisereduce)."
        )

    mic: devices.Microphone | None = None
    if capture_mic:
        mic = ui.select_microphone(
            devices.list_microphones(),
            devices.default_microphone(),
        )

    default_name = f"Audio da Reuniao {datetime.now():%d-%m-%Y %H-%M}"
    name, max_mb = ui.prompt_output_settings(default_name)

    settings.default_output_dir.mkdir(parents=True, exist_ok=True)
    recording = RecordingConfig(
        capture_mic=capture_mic,
        capture_pc=capture_pc,
        output_dir=settings.default_output_dir,
        file_name=f"{name}.wav",
        max_bytes=RecordingConfig.bytes_from_megabytes(max_mb),
    )
    post_config = PostProcessConfig(
        apply_ducking=apply_ducking,
        apply_noise_reduction=apply_nr,
    )

    ui.show_configuration(
        mic_name=mic.name if mic is not None else None,
        capture_mic=capture_mic,
        capture_pc=capture_pc,
        apply_ducking=apply_ducking,
        apply_noise_reduction=apply_nr,
        output_path=str(recording.output_path),
        max_mb=max_mb,
    )

    recorder = AudioRecorder(mic, recording, settings.audio_config(), logger=log)
    _record_loop(recorder)

    if recorder.error is not None:
        ui.print_error(f"A gravação terminou com erro: {recorder.error}")

    files = recorder.generated_files
    ui.show_summary(files)

    if post_config.is_enabled and files:
        _run_postprocessing(files, post_config)


def _record_loop(recorder: AudioRecorder) -> None:
    """Inicia a gravação e processa o teclado até o usuário encerrar."""
    recorder.start()
    timer = ElapsedTimer()

    if not keyboard.keyboard_available():
        ui.print_warning(
            "Leitura de teclas indisponível nesta plataforma — use Ctrl+C para encerrar."
        )

    try:
        with ui.RecordingDashboard(
            capture_mic=recorder.capture_mic,
            capture_pc=recorder.capture_pc,
        ) as dashboard:
            while recorder.is_running():
                dashboard.update(
                    paused=recorder.is_paused(),
                    elapsed=timer.elapsed(),
                    mic_level=recorder.mic_level,
                    pc_level=recorder.pc_level,
                )
                _handle_key(recorder, timer)
                time.sleep(_POLL_INTERVAL)
    except KeyboardInterrupt:
        ui.print_warning("Interrupção forçada detectada (Ctrl+C).")
    finally:
        recorder.stop()


def _handle_key(recorder: AudioRecorder, timer: ElapsedTimer) -> None:
    """Trata uma eventual tecla pressionada (P = pausar, E = encerrar)."""
    key = keyboard.read_key()
    if key == "p":
        if recorder.toggle_pause():
            timer.pause()
        else:
            timer.resume()
    elif key == "e":
        recorder.stop()


def _run_postprocessing(files: list[Path], config: PostProcessConfig) -> None:
    """Aplica o pós-processamento a cada arquivo com barra de progresso."""
    ui.print_info("Iniciando pós-processamento (pode levar alguns segundos)...")
    with ui.postprocess_progress(len(files)) as (progress, task_id):
        for path in files:
            progress.update(task_id, description=f"Processando {path.name}")
            try:
                postprocess.process_file(path, config)
            except Exception as exc:  # noqa: BLE001 - reportar e seguir p/ próximo
                ui.print_error(f"Falha ao processar {path.name}: {exc}")
            progress.advance(task_id)


if __name__ == "__main__":
    run()
