"""Interface de terminal elegante baseada na biblioteca ``rich``.

Concentra toda a apresentação: banner, prompts de configuração, seleção de
microfone (tabela + prompt validado), o painel de status ao vivo (timer,
estado e medidores de nível) e a barra de progresso do pós-processamento.

A renderização ao vivo segue o padrão recomendado: uma função de render
constrói um :class:`rich.panel.Panel` de *altura fixa* a cada quadro e o
:class:`rich.live.Live` cuida do desenho (sem ``cls`` manual, sem
``print`` cru durante o ``Live`` — o que evita flicker).
"""

from __future__ import annotations

import math
from collections.abc import Iterator, Sequence
from contextlib import contextmanager

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
)
from rich.prompt import IntPrompt, Prompt
from rich.table import Table
from rich.text import Text

from .devices import Microphone

#: Console único compartilhado pela aplicação.
console: Console = Console()

_METER_WIDTH = 32
_DB_FLOOR = -60.0  # piso do medidor em dBFS


# ---------------------------------------------------------------------- #
# Telas estáticas e prompts
# ---------------------------------------------------------------------- #
def print_banner() -> None:
    """Exibe o banner de abertura da aplicação."""
    banner = Text.assemble(
        ("🎙️  AI-AUDIO-CAPTURE", "bold cyan"),
        ("  ·  ", "dim"),
        ("Gravador otimizado para IA (16 kHz)", "white"),
    )
    console.print(Panel(banner, border_style="cyan", padding=(1, 4)))


def prompt_capture_sources() -> tuple[bool, bool]:
    """Pergunta quais fontes de áudio devem ser capturadas.

    Returns
    -------
    tuple[bool, bool]
        ``(capturar_microfone, capturar_pc)`` para o modo escolhido.
    """
    console.print("\n[bold]Fontes de áudio[/bold]")
    console.print("  [cyan]1[/cyan]  Microfone + áudio do computador")
    console.print("  [cyan]2[/cyan]  Somente microfone")
    console.print("  [cyan]3[/cyan]  Somente áudio do computador")
    choice = IntPrompt.ask(
        "[cyan]Modo de captura[/cyan]",
        choices=["1", "2", "3"],
        default=1,
        show_choices=False,
    )
    capture_modes = ((True, True), (True, False), (False, True))
    return capture_modes[choice - 1]


def select_microphone(
    microphones: Sequence[Microphone],
    default: Microphone | None = None,
) -> Microphone:
    """Apresenta os microfones numa tabela e retorna o escolhido.

    Parameters
    ----------
    microphones:
        Dispositivos disponíveis (não vazio).
    default:
        Microfone padrão do sistema (destacado e usado como escolha padrão).

    Returns
    -------
    Microphone
        O dispositivo selecionado pelo usuário.

    Raises
    ------
    SystemExit
        Se a lista de microfones estiver vazia.
    """
    if not microphones:
        console.print("[bold red]✗ Nenhum microfone encontrado no sistema![/bold red]")
        raise SystemExit(1)
    if len(microphones) == 1:
        return microphones[0]

    default_id = getattr(default, "id", None)
    table = Table(title="Microfones disponíveis", header_style="bold cyan")
    table.add_column("#", justify="right", style="cyan", no_wrap=True)
    table.add_column("Dispositivo")
    table.add_column("Padrão", justify="center")

    default_index = 1
    for index, mic in enumerate(microphones, start=1):
        is_default = default_id is not None and mic.id == default_id
        if is_default:
            default_index = index
        table.add_row(str(index), mic.name, "★" if is_default else "")

    console.print(table)
    choice = IntPrompt.ask(
        "[cyan]Selecione o microfone[/cyan]",
        choices=[str(i) for i in range(1, len(microphones) + 1)],
        default=default_index,
        show_choices=False,
    )
    return microphones[choice - 1]


def prompt_output_settings(default_name: str) -> tuple[str, float]:
    """Pergunta o nome-base do arquivo e o tamanho máximo de cada parte.

    Returns
    -------
    tuple[str, float]
        ``(nome_base_sem_extensao, tamanho_max_mb)`` — ``0.0`` = sem divisão.
    """
    console.print("\n[bold]Configuração de saída[/bold]")
    name = Prompt.ask("Nome do arquivo (sem extensão)", default=default_name).strip()
    max_mb = _ask_float("Tamanho máximo de cada parte em MB (0 = sem limite)", default=0.0)
    return (name or default_name), max_mb


def _ask_float(prompt: str, default: float) -> float:
    """Lê um ``float`` não-negativo, reaproveitando o padrão em caso de erro."""
    raw = Prompt.ask(f"[cyan]{prompt}[/cyan]", default=str(default)).strip()
    try:
        value = float(raw.replace(",", "."))
    except ValueError:
        return default
    return value if value > 0 else 0.0


def show_configuration(
    *,
    mic_name: str | None,
    capture_mic: bool,
    capture_pc: bool,
    apply_ducking: bool,
    apply_noise_reduction: bool,
    output_path: str,
    max_mb: float,
) -> None:
    """Mostra um resumo da configuração antes de iniciar a gravação.

    Parameters
    ----------
    mic_name:
        Nome do microfone selecionado, ou ``None`` quando essa fonte está inativa.
    capture_mic:
        Se o microfone será capturado.
    capture_pc:
        Se o áudio do computador será capturado por *loopback*.
    apply_ducking:
        Se a redução de eco será aplicada ao modo combinado.
    apply_noise_reduction:
        Se a limpeza de ruído será aplicada ao microfone.
    output_path:
        Caminho-base do arquivo de saída.
    max_mb:
        Tamanho máximo de cada parte, em MB; ``0`` desativa a divisão.
    """
    table = Table.grid(padding=(0, 2))
    table.add_column(justify="right", style="cyan", no_wrap=True)
    table.add_column()
    table.add_row(
        "🎤 Microfone",
        _on_off(capture_mic, mic_name or "Ativado", "Desativado"),
    )
    table.add_row(
        "🔊 Áudio do PC",
        _on_off(capture_pc, "Ativado (loopback automático)", "Desativado"),
    )
    if capture_mic and capture_pc:
        table.add_row("🧹 Redução de eco", _on_off(apply_ducking))
    if capture_mic:
        table.add_row("✨ Limpeza de ruído", _on_off(apply_noise_reduction))
    table.add_row("💾 Arquivo base", output_path)
    if max_mb > 0:
        table.add_row("📏 Divisão", f"a cada {max_mb:g} MB")
    console.print(Panel(table, title="Configuração", border_style="green", padding=(1, 2)))


def _on_off(
    enabled: bool,
    on_label: str = "Ativada",
    off_label: str = "Desativada",
) -> Text:
    return Text(on_label if enabled else off_label, style="green" if enabled else "dim")


def print_info(message: str) -> None:
    """Imprime uma mensagem informativa fora do contexto ``Live``."""
    console.print(f"[cyan]ℹ[/cyan]  {message}")


def print_warning(message: str) -> None:
    """Imprime um aviso (ex.: dependência opcional ausente)."""
    console.print(f"[yellow]⚠[/yellow]  {message}")


def print_error(message: str) -> None:
    """Imprime uma mensagem de erro."""
    console.print(f"[bold red]✗[/bold red]  {message}")


def show_summary(files: Sequence[object]) -> None:
    """Mostra o resumo final com os arquivos gerados."""
    console.print(
        Panel(
            f"[bold green]✓ Concluído![/bold green] {len(files)} arquivo(s) gerado(s).",
            border_style="green",
        )
    )
    for path in files:
        console.print(f"   [green]•[/green] {path}")


# ---------------------------------------------------------------------- #
# Medidores de nível
# ---------------------------------------------------------------------- #
def _normalize_db(rms: float) -> float:
    """Mapeia o RMS (0–1) para a faixa ``_DB_FLOOR``–0 dB, normalizado 0–1."""
    decibels = 20.0 * math.log10(rms + 1e-9)
    return max(0.0, min(1.0, (decibels - _DB_FLOOR) / -_DB_FLOOR))


def _meter(level: float) -> Text:
    """Renderiza uma barra de nível colorida (verde/amarelo/vermelho)."""
    filled = int(round(level * _METER_WIDTH))
    if level < 0.7:
        color = "green"
    elif level < 0.9:
        color = "yellow"
    else:
        color = "red"
    bar = Text()
    bar.append("█" * filled, style=color)
    bar.append("─" * (_METER_WIDTH - filled), style="grey37")
    return bar


# ---------------------------------------------------------------------- #
# Painel de status ao vivo
# ---------------------------------------------------------------------- #
class RecordingDashboard:
    """Painel ``rich`` ao vivo com timer, estado e medidores de nível.

    Usado como gerenciador de contexto; ``update`` é chamado a cada iteração
    do laço principal. O ``Live`` interno cuida do redesenho.

    Parameters
    ----------
    capture_mic:
        Se ``True``, exibe o medidor do microfone.
    capture_pc:
        Se ``True``, exibe o medidor do áudio do PC.
    refresh_per_second:
        Frequência de atualização do ``Live`` (8–15 dá animação suave).
    """

    def __init__(
        self,
        capture_mic: bool,
        capture_pc: bool,
        refresh_per_second: int = 10,
    ) -> None:
        self._capture_mic = capture_mic
        self._capture_pc = capture_pc
        self._blink = True
        self._live = Live(
            self._render(paused=False, elapsed=0.0, mic_level=0.0, pc_level=0.0),
            console=console,
            refresh_per_second=refresh_per_second,
            screen=False,
            transient=False,
            redirect_stdout=False,
            redirect_stderr=False,
        )

    def __enter__(self) -> RecordingDashboard:
        """Inicia o display ao vivo e retorna o próprio painel."""
        self._live.__enter__()
        return self

    def __exit__(self, *exc_info: object) -> None:
        """Encerra o display ao vivo, restaurando o terminal."""
        self._live.__exit__(*exc_info)

    def update(
        self,
        *,
        paused: bool,
        elapsed: float,
        mic_level: float,
        pc_level: float,
    ) -> None:
        """Atualiza o painel com o estado atual da gravação."""
        self._blink = not self._blink
        self._live.update(
            self._render(
                paused=paused,
                elapsed=elapsed,
                mic_level=mic_level,
                pc_level=pc_level,
            )
        )

    def _render(
        self,
        *,
        paused: bool,
        elapsed: float,
        mic_level: float,
        pc_level: float,
    ) -> Panel:
        if paused:
            status = Text("  PAUSADO  ", style="bold black on yellow")
            border = "yellow"
        else:
            dot = "●" if self._blink else "○"
            status = Text(f" {dot} GRAVANDO ", style="bold white on red")
            border = "red"

        minutes, seconds = divmod(int(elapsed), 60)
        table = Table.grid(padding=(0, 2))
        table.add_column(justify="right", style="cyan", no_wrap=True)
        table.add_column(min_width=_METER_WIDTH + 4)
        table.add_row("Estado", status)
        table.add_row("Tempo", Text(f"{minutes:02d}:{seconds:02d}", style="bold"))
        if self._capture_mic:
            table.add_row("Microfone", _meter(_normalize_db(mic_level)))
        if self._capture_pc:
            table.add_row("Áudio PC", _meter(_normalize_db(pc_level)))
        table.add_row("Comandos", Text("[P] Pausar/Retomar   [E] Encerrar", style="dim"))

        return Panel(
            table,
            title="AI-AUDIO-CAPTURE",
            subtitle="gravador para IA",
            border_style=border,
            padding=(1, 2),
        )


# ---------------------------------------------------------------------- #
# Progresso do pós-processamento
# ---------------------------------------------------------------------- #
@contextmanager
def postprocess_progress(total: int) -> Iterator[tuple[Progress, TaskID]]:
    """Contexto com barra de progresso determinada para o pós-processamento.

    Parameters
    ----------
    total:
        Número de arquivos a processar.

    Yields
    ------
    tuple[rich.progress.Progress, rich.progress.TaskID]
        A barra e o identificador da *task* já criada; use
        ``progress.advance(task_id)`` para avançar.
    """
    progress = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
    )
    with progress:
        task_id = progress.add_task("Pós-processando", total=total)
        yield progress, task_id
