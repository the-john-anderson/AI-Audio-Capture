# AI-Audio-Capture 🎙️🤖

Um gravador de áudio interativo via linha de comando (CLI) desenvolvido em Python, projetado especificamente para gerar arquivos otimizados para transcrição por Inteligência Artificial (como OpenAI Whisper, Gemini, Claude, etc).

## 🌟 Diferenciais

- **Otimizado para IA**: Grava nativamente em **16kHz**, a taxa de amostragem padrão ouro para modelos de reconhecimento de fala.
- **Separação Estéreo Inteligente**:
  - **Canal Esquerdo (L)**: Captura o seu Microfone.
  - **Canal Direito (R)**: Captura o Áudio do Sistema (reuniões, vídeos, sons do PC).
  - *Isso permite que IAs identifiquem com precisão quem está falando.*
- **Interface Interativa**: Timer em tempo real, indicadores visuais e comandos sem necessidade de pressionar "Enter".
- **Controle Total**: Suporte a **Pausar** e **Retomar** a gravação no mesmo arquivo.

## 🚀 Como Usar

### Pré-requisitos

Você precisará do Python instalado e das seguintes bibliotecas:

```bash
pip install soundcard soundfile numpy
```

### Execução

1. Clone o repositório ou baixe o arquivo `main.py`.
2. Execute o script:
   ```bash
   python main.py
   ```
3. Siga as instruções na tela:
   - Escolha se deseja capturar o áudio do PC.
   - Selecione seu microfone.
   - Defina um nome para o arquivo (ou use o padrão com data/hora).

### Comandos durante a gravação

- `P`: Pausa ou Retoma a gravação.
- `E`: Encerra e salva o arquivo `.wav` final.

## 📂 Estrutura de Saída

Os arquivos são salvos no formato `.wav` (PCM_16), garantindo que não haja perda de qualidade por compressão antes do processamento pela IA.

## 🛠️ Tecnologias Utilizadas

- **Python 3**
- **SoundCard**: Para captura de áudio multicanal e loopback.
- **SoundFile**: Para escrita robusta de arquivos de áudio.
- **Numpy**: Para manipulação eficiente dos buffers de som.

---
Desenvolvido para facilitar o fluxo de trabalho de quem precisa de transcrições perfeitas e separação de fontes sonoras.
