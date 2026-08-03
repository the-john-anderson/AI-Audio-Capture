# AI-Audio-Capture 🎙️🤖

Gravador de áudio de terminal, em Python, projetado para produzir arquivos
**otimizados para transcrição por IA** (OpenAI Whisper, Gemini, Claude, etc.).
Grava o **microfone**, o **áudio do sistema** (loopback) ou ambos, em WAV
16 kHz.

> **Versão 2.0** — reescrita modular, com interface [`rich`](https://github.com/Textualize/rich),
> configuração validada (Pydantic), testes automatizados e empacotamento em
> executável Windows (`.exe`).

---

## 🌟 Diferenciais

- **Otimizado para IA**: grava nativamente em **16 kHz**, a taxa padrão-ouro
  para modelos de reconhecimento de fala.
- **Três modos de captura**: microfone + computador, somente microfone ou
  somente computador.
- **Separação estéreo inteligente** no modo combinado:
  - **Canal L** → seu microfone.
  - **Canal R** → áudio do sistema (reuniões, vídeos, sons do PC).
  - *Permite que a IA identifique com precisão quem está falando.*
- **Saída mono** quando apenas uma fonte é gravada, sem canal silencioso
  desnecessário.
- **Interface elegante**: painel ao vivo com timer, estado e **medidores de
  nível** (VU) em tempo real; seleção de microfone em tabela.
- **Robusto**: arquitetura multi-thread que trata *drift* de clock entre
  dispositivos, reconexão automática ao trocar o alto-falante padrão, e
  divisão de arquivos por tamanho.
- **Processamento para IA**: *dither* contínuo (estabiliza o ruído de fundo) e
  *soft limiter* (evita clipping) aplicados em tempo real.
- **Pós-processamento opcional**: redução de eco (*ducking*) e limpeza de
  ruído de fundo.

---

## 🚀 Início rápido

### Pré-requisitos

- **Python 3.10+** (testado em 3.14), **Windows** (a captura usa o WASAPI).

### Instalação

```powershell
# 1. Dependências de execução (núcleo)
pip install -r requirements.txt

# 2. (Opcional) Pós-processamento: redução de eco + de ruído
pip install -r requirements-postprocess.txt
```

### Execução

```powershell
python -m ai_audio_capture
# ou, de forma equivalente:
python main.py
```

Siga as instruções na tela:

1. Escolher **microfone + computador** (padrão), **somente microfone** ou
   **somente computador**.
2. Selecionar o microfone, quando ele fizer parte do modo escolhido.
3. Definir o nome do arquivo e, opcionalmente, o tamanho máximo por parte.

### Abrir por duplo clique no Windows

O aplicativo clicável recomendado é o build **completo**, no formato
`onedir`. Gere-o uma vez com:

```powershell
.\build\build_exe.ps1 -Full -Clean
```

Depois, abra por duplo clique o executável que fica na raiz do repositório:

```text
AI-Audio-Capture.exe
```

A janela de terminal faz parte da interface Rich e permanece aberta durante
a gravação. Esse arquivo é um launcher pequeno que encontra o bundle completo
automaticamente. Mantenha o launcher na raiz e a pasta `dist` em sua posição;
para mover o aplicativo, copie o repositório ou distribua o bundle inteiro.

### Comandos durante a gravação

| Tecla | Ação                         |
|:-----:|------------------------------|
| `P`   | Pausar / Retomar a gravação  |
| `E`   | Encerrar e salvar            |
| `Ctrl+C` | Interrupção forçada        |

Os arquivos `.wav` (PCM 16 bits) são salvos em
`~/Documents/Gravações de som PY`.

---

## 🧱 Arquitetura

O código é modular, com responsabilidades separadas:

| Módulo                       | Responsabilidade                                            |
|------------------------------|-------------------------------------------------------------|
| `ai_audio_capture/config.py` | Configurações validadas (Pydantic), cache de ambiente.      |
| `ai_audio_capture/devices.py`| Isola o `soundcard` (enumeração/seleção de dispositivos).   |
| `ai_audio_capture/processing.py` | DSP em tempo real (dither + soft limiter).              |
| `ai_audio_capture/recorder.py`   | Orquestrador multi-thread de captura e escrita.         |
| `ai_audio_capture/postprocess.py`| Ducking + redução de ruído (*lazy loading*).            |
| `ai_audio_capture/ui.py`     | Interface `rich` (banner, prompts, painel ao vivo).         |
| `ai_audio_capture/timing.py` | Cronômetro com pausa.                                       |
| `ai_audio_capture/keyboard.py`| Leitura de teclas não-bloqueante (Windows).                |
| `ai_audio_capture/app.py`    | Fluxo principal (ponto de entrada `run`).                   |

### Pipeline de threads

```
┌───────────┐    ┌──────────┐
│ mic_worker│───▶│ q_mic    │─┐  (quando o microfone está ativo)
└───────────┘    └──────────┘ │   ┌────────────────┐    ┌───────────┐    ┌──────────────┐
                              ├──▶│ process_worker │───▶│ q_disco   │───▶│ writer_worker│──▶ WAV
┌───────────┐    ┌──────────┐ │   │ (DSP + níveis) │    └───────────┘    │ (split p/ MB)│
│ pc_worker │───▶│ q_pc     │─┘   └────────────────┘                     └──────────────┘
└───────────┘    └──────────┘
```

O `pc_worker` também só é iniciado quando o áudio do computador está ativo.
No modo combinado, o processador preserva a ordem `[microfone, computador]`;
nos modos individuais, encaminha somente a fonte selecionada.

**Por que threading e não `asyncio`?** `soundcard.record()` é uma chamada
nativa *bloqueante* (WASAPI) que libera a GIL — threads leem os dois
dispositivos de forma realmente concorrente. `asyncio` exigiria delegar a um
*executor* (threads, de novo), adicionando latência sem benefício para este
I/O de áudio em tempo real.

### Configuração via ambiente

Variáveis com o prefixo `AAC_` (ou um arquivo `.env`) sobrescrevem os padrões:

```powershell
$env:AAC_LOG_LEVEL = "DEBUG"
$env:AAC_DEFAULT_OUTPUT_DIR = "D:\Gravacoes"
python -m ai_audio_capture
```

---

## 🖥️ Gerar o executável Windows (.exe)

O empacotamento usa **PyInstaller ≥ 6.17** (necessário para Python 3.14).
Há dois perfis:

| Perfil    | Conteúdo                                  | Tamanho | Início |
|-----------|-------------------------------------------|--------:|-------:|
| **Completo** (recomendado) | inclui redução de ruído (`noisereduce`) | maior | normal |
| **Leve** | mic + PC + ducking (scipy), **sem** redução de ruído | pequeno | rápido |

### Forma mais simples (script)

```powershell
# (opcional) gerar o ícone personalizado primeiro
pip install pillow
python build\make_icon.py

# Aplicativo completo recomendado, do zero:
.\build\build_exe.ps1 -Full -Clean

# Alternativa leve, também numa pasta:
.\build\build_exe.ps1
```

O script cria um ambiente virtual isolado (`.venv-build`), instala as
dependências, gera o bundle escolhido e cria o launcher clicável
`AI-Audio-Capture.exe` na raiz:

- Completo: `dist\AI-Audio-Capture-full\AI-Audio-Capture-full.exe`.
- Leve: `dist\AI-Audio-Capture\AI-Audio-Capture.exe`.

Para uso local, basta clicar em `AI-Audio-Capture.exe`. O launcher prefere o
perfil recém-gerado e abre o bundle sem depender do diretório atual. Para
distribuição, envie o launcher junto com a pasta `dist`; ele não contém os
arquivos pesados do aplicativo.

Para recriar somente o launcher, sem repetir o empacotamento:

```powershell
.\build\build_launcher.ps1 -Profile Full
```

### Forma manual

```powershell
pip install "pyinstaller>=6.17"
python build\make_icon.py                                   # opcional
pyinstaller build\AI-Audio-Capture.spec --noconfirm         # leve
# ou
pyinstaller build\AI-Audio-Capture-full.spec --noconfirm    # completo
```

### Notas de empacotamento

- **Não desabilite os hooks** do PyInstaller: `soundcard`, `soundfile` e
  `scipy` trazem hooks próprios que incluem DLLs e o header
  `mediafoundation.py.h` (lido pelo `cffi` no import). Sem ele, o `.exe` falha
  ao listar dispositivos.
- Os specs geram somente **onedir**. Isso evita extrair a pilha pesada no
  `%TEMP%` a cada execução e exige que a pasta `dist` permaneça intacta. O
  launcher da raiz apenas abre esse bundle.
- O build deve ser `--console` (app interativo). Já está configurado nos specs.
- **Teste o `.exe` em uma máquina sem Python** para confirmar que o bundle
  está completo.

---

## 🧪 Desenvolvimento e testes

```powershell
pip install -r requirements-dev.txt

# Rodar os testes (sem hardware — o soundcard é simulado)
pytest

# Lint / estilo (PEP 8, imports, docstrings, type hints)
ruff check main.py ai_audio_capture build tests
ruff format --check main.py ai_audio_capture build tests
```

Os testes cobrem: validação de configuração, DSP (dither/limiter/RMS),
cronômetro com pausa, leitura de teclado, ducking/redução de ruído,
isolamento do `soundcard` e o pipeline multi-thread completo (incluindo a
divisão de arquivos por tamanho), usando dublês determinísticos.

---

## 🛠️ Tecnologias

- **SoundCard** — captura multicanal e *loopback* (WASAPI).
- **SoundFile** — escrita robusta de WAV (PCM 16 bits).
- **NumPy** — manipulação dos buffers de áudio.
- **Rich** — interface de terminal.
- **Pydantic** — configuração validada.
- **SciPy** / **noisereduce** *(opcionais)* — pós-processamento.

---

Desenvolvido para quem precisa de transcrições precisas com separação de
fontes sonoras.
