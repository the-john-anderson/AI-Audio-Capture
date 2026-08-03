"""Orquestrador multi-thread de captura e gravação de áudio.

Resolve o *drift* de relógio entre dispositivos lendo as fontes habilitadas
em threads independentes e sincronizando-as por filas. A arquitetura tem até
quatro estágios:

1. ``_mic_worker``  — lê o microfone → ``_mic_queue``.
2. ``_pc_worker``   — lê o *loopback* do PC → ``_pc_queue`` (reconecta ao
   dispositivo padrão quando ele muda).
3. ``_process_worker`` — sincroniza as duas filas, aplica DSP e publica os
   níveis (RMS) para a UI → ``_disk_queue``.
4. ``_writer_worker`` — escreve em disco, dividindo por tamanho se pedido.

Por que threading e não asyncio? ``soundcard.record()`` é uma chamada nativa
*bloqueante* (WASAPI) que libera a GIL; threads leem os dois dispositivos de
forma realmente concorrente, enquanto ``asyncio`` exigiria delegar a um
*executor* (threads, de novo) com latência extra. Threading é a escolha
correta para este I/O de áudio em tempo real.

Notas de concorrência
---------------------
* Parada e pausa usam :class:`threading.Event` (visibilidade entre threads
  garantida), substituindo o dicionário compartilhado sem sincronização do
  código original.
* Frames descartados por filas cheias são contabilizados e logados
  periodicamente — sem perda silenciosa de dados.
* Em :meth:`stop`, produtores, processamento e escritor são encerrados em
  estágios; cada consumidor drena sua fila antes de o estágio seguinte parar.
"""

from __future__ import annotations

import os
import queue
import threading
import time
from collections.abc import Callable
from logging import Logger
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from . import devices
from .config import AudioConfig, RecordingConfig
from .logging_setup import get_logger
from .processing import AudioProcessor, FloatArray, compute_rms

#: Subtipo WAV forçado: garante PCM de 16 bits (2 bytes/amostra), tornando o
#: cálculo de divisão por tamanho exato e a saída previsível para a IA.
_WAV_SUBTYPE = "PCM_16"
_BYTES_PER_SAMPLE = 2

# Capacidades de fila (em blocos). Mantêm latência baixa sem estourar memória.
_HW_QUEUE_SIZE = 30
_DISK_QUEUE_SIZE = 150
#: Acima deste acúmulo numa fila de hardware, descarta-se 1 bloco extra
#: (correção suave de *drift* de relógio).
_DRIFT_SLACK = 5
#: A cada N descartes de um mesmo tipo, registra-se um aviso agregado.
_DROP_LOG_EVERY = 100
#: Prazo total para encerrar todos os estágios do pipeline.
_STOP_TIMEOUT = 10.0


class AudioRecorder:
    """Captura as fontes de áudio habilitadas e grava em WAV.

    Parameters
    ----------
    mic:
        Dispositivo selecionado ou ``None`` quando o microfone está desativado.
    recording:
        Configuração das fontes, destino e divisão dos arquivos.
    audio:
        Parâmetros de captura/DSP (taxa, tamanho de bloco, dither, limiter).
    logger:
        Logger opcional; por padrão usa o logger do módulo.
    """

    def __init__(
        self,
        mic: devices.Microphone | None,
        recording: RecordingConfig,
        audio: AudioConfig | None = None,
        *,
        logger: Logger | None = None,
    ) -> None:
        if recording.capture_mic and mic is None:
            raise ValueError("Um dispositivo de microfone é obrigatório neste modo.")

        self._mic = mic
        self._recording = recording
        self._audio = audio or AudioConfig()
        self._log = logger or get_logger(__name__)
        self._processor = AudioProcessor(self._audio)

        # Sinalização em estágios: captura → processamento → escrita.
        self._capture_stop_event = threading.Event()
        self._captures_done_event = threading.Event()
        self._processing_done_event = threading.Event()
        self._pause_event = threading.Event()

        # Filas: hardware (mic/pc) → processamento → disco.
        self._mic_queue: queue.Queue[FloatArray] = queue.Queue(maxsize=_HW_QUEUE_SIZE)
        self._pc_queue: queue.Queue[FloatArray] = queue.Queue(maxsize=_HW_QUEUE_SIZE)
        self._disk_queue: queue.Queue[FloatArray] = queue.Queue(maxsize=_DISK_QUEUE_SIZE)

        self._capture_threads: list[threading.Thread] = []
        self._process_thread: threading.Thread | None = None
        self._writer_thread: threading.Thread | None = None
        self._lifecycle_lock = threading.Lock()
        self._stop_lock = threading.Lock()
        self._started = False
        self._finished = False
        self._generated_files: list[Path] = []
        self._error: Exception | None = None

        # Níveis publicados para a UI (leitura/escrita atômica de float).
        self.mic_level: float = 0.0
        self.pc_level: float = 0.0

        # Contadores de frames descartados (filas cheias).
        self._drops: dict[str, int] = {"mic": 0, "pc": 0, "disk": 0}

    # ------------------------------------------------------------------ #
    # API pública
    # ------------------------------------------------------------------ #
    @property
    def generated_files(self) -> list[Path]:
        """Lista (cópia) dos arquivos gerados até o momento."""
        return list(self._generated_files)

    @property
    def error(self) -> Exception | None:
        """Última exceção fatal de um *worker*, se houver."""
        return self._error

    @property
    def capture_mic(self) -> bool:
        """``True`` se a captura do microfone está habilitada."""
        return self._recording.capture_mic

    @property
    def capture_pc(self) -> bool:
        """``True`` se a captura do áudio do PC está habilitada."""
        return self._recording.capture_pc

    def is_running(self) -> bool:
        """``True`` após iniciar e antes de uma solicitação de parada."""
        return self._started and not self._capture_stop_event.is_set()

    def is_paused(self) -> bool:
        """``True`` se a gravação está pausada."""
        return self._pause_event.is_set()

    def toggle_pause(self) -> bool:
        """Alterna entre pausado/gravando e retorna o novo estado pausado."""
        if self._pause_event.is_set():
            self._pause_event.clear()
            paused = False
        else:
            self._pause_event.set()
            paused = True
        self._log.info("Gravação %s.", "pausada" if paused else "retomada")
        return paused

    def start(self) -> None:
        """Inicia uma única vez os estágios necessários para as fontes ativas.

        Raises
        ------
        RuntimeError
            Se esta instância já tiver sido iniciada anteriormente.
        """
        with self._lifecycle_lock:
            if self._started:
                raise RuntimeError("Esta instância de AudioRecorder já foi iniciada.")
            self._started = True

        self._log.info("Iniciando gravação multi-thread.")
        try:
            self._writer_thread = self._spawn(self._writer_worker, "writer")
            self._process_thread = self._spawn(self._process_worker, "process")
            if self._recording.capture_mic:
                self._capture_threads.append(self._spawn(self._mic_worker, "mic"))
            if self._recording.capture_pc:
                self._capture_threads.append(self._spawn(self._pc_worker, "pc-loopback"))
        except Exception as exc:
            self._fail(exc, "inicialização das threads")
            self.stop()
            raise

    def stop(self) -> None:
        """Para a gravação e aguarda o término de todas as threads.

        Idempotente: chamadas repetidas são seguras. Os produtores são
        encerrados antes do escritor, que drena a fila de disco restante.
        """
        with self._stop_lock:
            if not self._started or self._finished:
                return

            self._log.info("Sinalizando parada ao orquestrador.")
            self._capture_stop_event.set()
            deadline = time.monotonic() + _STOP_TIMEOUT

            capture_results = [
                self._join_until(thread, deadline) for thread in self._capture_threads
            ]
            captures_stopped = all(capture_results)
            if not captures_stopped:
                return

            self._captures_done_event.set()
            if self._process_thread is not None and not self._join_until(
                self._process_thread, deadline
            ):
                return

            # O worker define este evento em ``finally``. Também o definimos
            # se a criação da thread falhou antes de ela existir.
            self._processing_done_event.set()
            if self._writer_thread is not None and not self._join_until(
                self._writer_thread, deadline
            ):
                return

            self._finished = True
            self._log_drops_summary()
            self._log.info(
                "Gravação finalizada. %d arquivo(s) gerado(s).",
                len(self._generated_files),
            )

    # ------------------------------------------------------------------ #
    # Infraestrutura interna
    # ------------------------------------------------------------------ #
    def _spawn(self, target: Callable[[], None], name: str) -> threading.Thread:
        """Inicia e retorna uma thread daemon nomeada."""
        thread = threading.Thread(target=target, name=name, daemon=True)
        thread.start()
        return thread

    def _join_until(self, thread: threading.Thread, deadline: float) -> bool:
        """Aguarda ``thread`` usando o prazo global e informa se ela encerrou."""
        thread.join(timeout=max(0.0, deadline - time.monotonic()))
        if thread.is_alive():
            self._log.error("Thread %s não encerrou no tempo limite.", thread.name)
            return False
        return True

    def _fail(self, exc: Exception, context: str) -> None:
        """Registra uma falha fatal de *worker* e sinaliza parada global."""
        self._log.error("Falha fatal em %s: %s", context, exc)
        if self._error is None:
            self._error = exc
        self._capture_stop_event.set()

    def _offer(self, target: queue.Queue[FloatArray], item: FloatArray, kind: str) -> None:
        """Enfileira ``item`` sem bloquear, contabilizando descartes."""
        try:
            target.put_nowait(item)
        except queue.Full:
            count = self._drops[kind] = self._drops[kind] + 1
            if count % _DROP_LOG_EVERY == 0:
                self._log.warning("Fila '%s' cheia — %d frame(s) descartado(s).", kind, count)

    def _log_drops_summary(self) -> None:
        total = sum(self._drops.values())
        if total:
            self._log.info(
                "Frames descartados na sessão — mic=%(mic)d pc=%(pc)d disco=%(disk)d.",
                self._drops,
            )

    # ------------------------------------------------------------------ #
    # Workers de hardware
    # ------------------------------------------------------------------ #
    def _mic_worker(self) -> None:
        """Lê o microfone isoladamente e enfileira os blocos."""
        self._log.info("Thread de microfone iniciada.")
        block = self._audio.block_size
        mic = self._mic
        if mic is None:
            self._fail(
                RuntimeError("Microfone ausente para uma captura habilitada."),
                "captura de microfone",
            )
            return
        try:
            with mic.recorder(samplerate=self._audio.sample_rate, channels=1) as stream:
                while not self._capture_stop_event.is_set():
                    self._offer(self._mic_queue, stream.record(numframes=block), "mic")
        except Exception as exc:  # noqa: BLE001 - falha de hardware é fatal aqui
            self._fail(exc, "captura de microfone")

    def _pc_worker(self) -> None:
        """Lê o *loopback* do PC, reconectando quando o dispositivo muda."""
        self._log.info("Thread de loopback (PC) iniciada.")
        block = self._audio.block_size
        # Verifica o dispositivo padrão a cada ~2 s.
        check_interval = max(1, round(2 * self._audio.sample_rate / block))

        stream: Any = None
        try:
            speaker_id = devices.default_speaker_id()
            stream = self._open_loopback(speaker_id)
            counter = 0

            while not self._capture_stop_event.is_set():
                counter += 1
                if counter >= check_interval:
                    counter = 0
                    speaker_id, stream = self._maybe_reconnect(speaker_id, stream)

                try:
                    data = stream.record(numframes=block)
                except Exception as exc:  # noqa: BLE001 - reabre inclusive o mesmo dispositivo
                    self._log.warning("Erro ao ler loopback; reconectando: %s", exc)
                    self._close_loopback(stream)
                    stream = None
                    if self._capture_stop_event.wait(0.1):
                        break
                    speaker_id = devices.default_speaker_id()
                    stream = self._open_loopback(speaker_id)
                    counter = 0
                    continue
                self._offer(self._pc_queue, data, "pc")
        except Exception as exc:  # noqa: BLE001
            self._fail(exc, "captura de loopback")
        finally:
            self._close_loopback(stream)

    def _open_loopback(self, speaker_id: Any) -> Any:
        """Abre (entra no contexto de) o gravador de *loopback*."""
        recorder_ctx = devices.loopback_for_speaker(speaker_id).recorder(
            samplerate=self._audio.sample_rate, channels=1
        )
        recorder_ctx.__enter__()
        return recorder_ctx

    def _close_loopback(self, stream: Any) -> None:
        """Fecha o gravador de *loopback*, registrando falhas de fechamento."""
        if stream is None:
            return
        try:
            stream.__exit__(None, None, None)
        except Exception as exc:  # noqa: BLE001 - não mascarar com 'except: pass'
            self._log.warning("Falha ao fechar stream de loopback: %s", exc)

    def _maybe_reconnect(self, speaker_id: Any, stream: Any) -> tuple[Any, Any]:
        """Reabre o *loopback* se o alto-falante padrão tiver mudado."""
        try:
            new_id = devices.default_speaker_id()
        except devices.DeviceError as exc:
            self._log.warning("Não foi possível checar o dispositivo padrão: %s", exc)
            return speaker_id, stream

        if new_id == speaker_id:
            return speaker_id, stream

        self._log.info("Mudança de dispositivo detectada. Reconectando loopback.")
        self._close_loopback(stream)
        return new_id, self._open_loopback(new_id)

    # ------------------------------------------------------------------ #
    # Processamento e escrita
    # ------------------------------------------------------------------ #
    def _process_worker(self) -> None:
        """Sincroniza as filas, aplica DSP e publica níveis para a UI."""
        self._log.info("Thread de processamento iniciada.")
        primary_queue = self._mic_queue if self._recording.capture_mic else self._pc_queue
        primary_is_mic = self._recording.capture_mic

        try:
            while not self._captures_done_event.is_set() or not primary_queue.empty():
                try:
                    primary = primary_queue.get(timeout=0.1)
                except queue.Empty:
                    continue

                primary = self._drain_extra(primary_queue, primary)
                if primary_is_mic:
                    audio_mic = primary
                    audio_pc = self._collect_pc(audio_mic)
                else:
                    audio_mic = None
                    audio_pc = primary

                if audio_mic is not None:
                    self.mic_level = compute_rms(audio_mic)
                if audio_pc is not None:
                    self.pc_level = compute_rms(audio_pc)

                if self._pause_event.is_set():
                    continue  # mantém as filas drenadas, mas não grava

                processed = self._processor.process_chunk(audio_mic, audio_pc)
                self._offer(self._disk_queue, processed, "disk")
        except Exception as exc:  # noqa: BLE001 - falha no estágio encerra o pipeline
            self._fail(exc, "processamento de áudio")
        finally:
            self._processing_done_event.set()

    def _collect_pc(self, audio_mic: FloatArray) -> FloatArray | None:
        """Obtém o bloco do PC alinhado; preenche com silêncio se faltar."""
        if not self._recording.capture_pc:
            return None
        try:
            audio_pc = self._pc_queue.get(timeout=0.05)
        except queue.Empty:
            # Dessincronia transitória: silêncio evita engasgar o microfone.
            return np.zeros_like(audio_mic)
        return self._drain_extra(self._pc_queue, audio_pc)

    @staticmethod
    def _drain_extra(source: queue.Queue[FloatArray], current: FloatArray) -> FloatArray:
        """Descarta 1 bloco extra se a fila acumulou (correção de *drift*)."""
        if source.qsize() > _DRIFT_SLACK:
            try:
                return source.get_nowait()
            except queue.Empty:
                return current
        return current

    def _writer_worker(self) -> None:
        """Consome a fila de disco e grava WAV, dividindo por tamanho."""
        self._log.info("Thread de escrita iniciada.")
        channels = self._recording.channels
        bytes_per_frame = channels * _BYTES_PER_SAMPLE
        max_bytes = self._recording.max_bytes

        part = 1
        frames_in_part = 0
        current_path = self._part_path(part)
        try:
            sound_file = self._open_sound_file(current_path, channels)
        except Exception as exc:  # noqa: BLE001 - sem arquivo, nada a gravar
            self._fail(exc, "abertura do arquivo de saída")
            return

        try:
            # Continua enquanto houver processamento OU chunks pendentes.
            while not self._processing_done_event.is_set() or not self._disk_queue.empty():
                try:
                    chunk = self._disk_queue.get(timeout=0.1)
                except queue.Empty:
                    continue

                if max_bytes > 0 and frames_in_part > 0:
                    chunk_bytes = len(chunk) * bytes_per_frame
                    if frames_in_part * bytes_per_frame + chunk_bytes > max_bytes:
                        # Só rola para nova parte se a atual já tem conteúdo;
                        # evita criar uma parte vazia quando um único chunk já
                        # excede o limite (que então é gravado nesta parte).
                        self._close_sound_file(sound_file)
                        part += 1
                        current_path = self._part_path(part)
                        sound_file = self._open_sound_file(current_path, channels)
                        frames_in_part = 0

                sound_file.write(chunk)
                frames_in_part += len(chunk)
        except Exception as exc:  # noqa: BLE001
            self._fail(exc, "escrita em disco")
        finally:
            self._close_sound_file(sound_file)

    def _open_sound_file(self, path: Path, channels: int) -> sf.SoundFile:
        """Abre um novo arquivo WAV PCM_16 e o registra como gerado."""
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = sf.SoundFile(
            os.fspath(path),
            mode="w",
            samplerate=self._audio.sample_rate,
            channels=channels,
            subtype=_WAV_SUBTYPE,
        )
        self._generated_files.append(path)
        self._log.info("Gravando em %s", path.name)
        return handle

    def _close_sound_file(self, handle: sf.SoundFile) -> None:
        """Fecha o arquivo de saída, registrando falhas de fechamento."""
        try:
            handle.close()
        except Exception as exc:  # noqa: BLE001 - não travar o encerramento
            self._log.error("Falha ao fechar arquivo de saída: %s", exc)

    def _part_path(self, part: int) -> Path:
        """Calcula o caminho da parte ``part`` (sem sufixo se sem divisão)."""
        base = self._recording.output_path
        if self._recording.max_bytes <= 0:
            return base
        return base.with_name(f"{base.stem}_parte{part}{base.suffix}")
