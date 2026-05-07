import soundcard as sc
import soundfile as sf
import numpy as np
import threading
import os
import sys
import msvcrt
import time
import warnings
from datetime import datetime

# Ignora avisos da placa de som (ex: "data discontinuity") para não poluir a tela
warnings.filterwarnings("ignore", message="data discontinuity in recording")

# Configurações ideais para IA (Whisper, GPT)
TAXA_AMOSTRAGEM = 16000

# Variáveis globais de controle de estado
estado = {
    'pausado': False,
    'encerrado': False
}
dados_gravados = []

def limpar_tela():
    """Limpa o console de forma cruzada (Windows/Linux/Mac)."""
    os.system('cls' if os.name == 'nt' else 'clear')

def exibir_cabecalho():
    """Exibe o cabeçalho estilizado do aplicativo."""
    limpar_tela()
    print("=" * 60)
    print("🎙️   AI-AUDIO-CAPTURE | GRAVADOR PARA IA  🤖".center(60))
    print("=" * 60)
    print()

def listar_microfones():
    """Lista e permite a seleção de um microfone disponível."""
    mics = sc.all_microphones()
    if not mics:
        print("❌ Nenhum microfone encontrado no sistema!")
        sys.exit(1)
    
    # Se houver apenas 1, já retorna ele sem perguntar
    if len(mics) == 1:
        return mics[0]
        
    print("--- Seleção de Microfone ---")
    for i, mic in enumerate(mics):
        print(f"[{i + 1}] {mic.name}")
        
    while True:
        try:
            escolha = input(f"\nSelecione o microfone (1 a {len(mics)}) ou pressione Enter para padrão: ").strip()
            
            # Se apertar Enter sem digitar nada, usa o default
            if not escolha:
                return sc.default_microphone()
                
            escolha = int(escolha)
            if 1 <= escolha <= len(mics):
                return mics[escolha - 1]
            print("⚠️ Seleção inválida. Tente novamente.")
        except ValueError:
            print("⚠️ Entrada inválida. Digite um número válido.")

def thread_gravacao(mic, loopback, nome_arquivo):
    """
    Função que roda em segundo plano capturando o áudio.
    """
    global dados_gravados, estado
    
    try:
        # Prepara o gravador do microfone
        mic_recorder = mic.recorder(samplerate=TAXA_AMOSTRAGEM, channels=1)
        
        if loopback:
            # Prepara o gravador do alto-falante (loopback/PC)
            pc_recorder = loopback.recorder(samplerate=TAXA_AMOSTRAGEM, channels=1)
            
            # Abre as duas streams ao mesmo tempo
            with mic_recorder as mic_stream, pc_recorder as pc_stream:
                while not estado['encerrado']:
                    # O record() bloqueia a execução até ler 1024 frames. 
                    # Fazemos a leitura contínua mesmo pausado para esvaziar o buffer da placa de som
                    audio_mic = mic_stream.record(numframes=1024)
                    audio_pc = pc_stream.record(numframes=1024)
                    
                    if not estado['pausado']:
                        # Salva em Stereo: Canal Esquerdo = Mic, Canal Direito = PC
                        # Em vez de misturar, concatenamos lado a lado no array.
                        stereo_frame = np.concatenate((audio_mic, audio_pc), axis=1)
                        stereo_frame = np.clip(stereo_frame, -1.0, 1.0)
                        dados_gravados.append(stereo_frame)
        else:
            # Apenas o microfone
            with mic_recorder as mic_stream:
                while not estado['encerrado']:
                    audio_mic = mic_stream.record(numframes=1024)
                    
                    if not estado['pausado']:
                        mix = np.clip(audio_mic, -1.0, 1.0)
                        dados_gravados.append(mix)

    except Exception as e:
        print(f"\n❌ Erro crítico durante a gravação na placa de som: {e}")
        estado['encerrado'] = True

def main():
    global estado, dados_gravados
    
    exibir_cabecalho()
    
    # 1. Configurar Áudio do PC
    capturar_pc_input = input("Deseja capturar também o áudio do computador? (S/n): ").strip().lower()
    capturar_pc = capturar_pc_input != 'n' # Considera "Sim" por padrão se o usuário apenas der Enter
    
    loopback = None
    if capturar_pc:
        speaker = sc.default_speaker()
        loopback = sc.get_microphone(id=speaker.id, include_loopback=True)
    print()
    
    # 2. Configurar Microfone
    mic = listar_microfones()
    
    # 3. Configurar Arquivo de Saída
    print("\n--- Configuração de Saída ---")
    data_hora = datetime.now().strftime("%d-%m-%Y %H-%M")
    nome_padrao = f"Audio da Reunião {data_hora}"
    nome_input = input(f"Nome do arquivo sem extensão [padrão: '{nome_padrao}']: ").strip()
    nome_arquivo = f"{nome_input if nome_input else nome_padrao}.wav"
    
    # 4. Tela de Resumo e Preparação
    exibir_cabecalho()
    print("⚙️   PREPARANDO DISPOSITIVOS...")
    print(f"🎤  Microfone: {mic.name}")
    if capturar_pc:
        print(f"🔊  Áudio PC:  {loopback.name}")
    print(f"💾  Arquivo:   {nome_arquivo}")
    print("-" * 60)
    
    # 5. Inicia a Thread de Gravação
    t = threading.Thread(target=thread_gravacao, args=(mic, loopback, nome_arquivo))
    t.start()
    
    # 6. Interface de Controle
    print("▶️   GRAVAÇÃO INICIADA COM SUCESSO")
    print("=" * 60)
    print("  Comandos rápidos (pressione a tecla, não precisa de Enter):")
    print("  [P] : Pausar / Retomar gravação")
    print("  [E] : Encerrar gravação e salvar")
    print("-" * 60)
    print() # linha que será usada para exibir o status dinamicamente
    
    inicio_gravacao = time.time()
    tempo_pausado_total = 0
    inicio_pausa = 0
    
    # Loop aguardando comandos do usuário (dinâmico e não-bloqueante)
    try:
        while not estado['encerrado']:
            if estado['pausado']:
                # Calcula o tempo total útil parado na hora da pausa
                duracao = (inicio_pausa - inicio_gravacao) - tempo_pausado_total
                status = "⏸️   PAUSADO  "
            else:
                # Calcula tempo correndo
                duracao = (time.time() - inicio_gravacao) - tempo_pausado_total
                dots = ["🔴", "⚪"]
                dot = dots[int(time.time() * 2) % 2]
                status = f"{dot}  GRAVANDO "
                
            minutos = int(duracao // 60)
            segundos = int(duracao % 60)
            
            # Reescreve a linha do terminal (\r retorna o cursor ao início da linha)
            sys.stdout.write(f"\r  {status} | ⏱️  Tempo: {minutos:02d}:{segundos:02d} | ⌨️  [P] Pausar [E] Encerrar     ")
            sys.stdout.flush()
            
            # Captura de tecla silenciosa (apenas no Windows)
            if msvcrt.kbhit():
                key = msvcrt.getch().decode('utf-8', 'ignore').lower()
                
                if key == 'p':
                    estado['pausado'] = not estado['pausado']
                    if estado['pausado']:
                        inicio_pausa = time.time()
                    else:
                        tempo_pausado_total += (time.time() - inicio_pausa)
                elif key == 'e':
                    estado['encerrado'] = True
            
            time.sleep(0.1) # Pausa curta para não sobrecarregar a CPU
                
    except KeyboardInterrupt:
        # Se o usuário der Ctrl+C, tratamos graciosamente
        print("\n\n  ⏹️  Interrupção forçada detectada (Ctrl+C).")
        estado['encerrado'] = True
    
    # 7. Finalização
    print("\n⏹️   Encerrando a conexão de áudio. Aguarde...")
    t.join() # Aguarda a thread fechar as streams de áudio com segurança
    
    if dados_gravados:
        # Concatena todos os pequenos blocos de 1024 frames num array gigante
        audio_final = np.concatenate(dados_gravados, axis=0)
        
        # Salva o disco
        sf.write(nome_arquivo, audio_final, TAXA_AMOSTRAGEM)
        print("=" * 60)
        print(f"✅  SUCESSO! Arquivo salvo como: {nome_arquivo}")
        print(f"⏱️  Tamanho total de frames: {len(audio_final)}")
        print("=" * 60)
    else:
        print("⚠️  Nenhum áudio foi capturado (talvez você tenha pausado imediatamente?).")

if __name__ == "__main__":
    main()