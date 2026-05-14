import soundcard as sc
import soundfile as sf
import numpy as np
import threading
import queue
import os
import sys
import msvcrt
import time
import warnings
import logging
from datetime import datetime

# Ignora avisos da placa de som (ex: "data discontinuity") para não poluir o log e tela
warnings.filterwarnings("ignore", message="data discontinuity in recording")

# Tenta carregar scipy para os filtros do Ducking e pós-processamento
try:
    from scipy.signal import lfilter, butter, filtfilt
except ImportError:
    lfilter = None
    butter = None
    filtfilt = None

# Tenta carregar noisereduce para pós-processamento
try:
    import noisereduce as nr
except ImportError:
    nr = None

# Configurações ideais para IA (Whisper, GPT)
TAXA_AMOSTRAGEM = 16000

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
        logging.error("Nenhum microfone encontrado.")
        sys.exit(1)
    
    if len(mics) == 1:
        return mics[0]
        
    print("--- Seleção de Microfone ---")
    for i, mic in enumerate(mics):
        print(f"[{i + 1}] {mic.name}")
        
    while True:
        try:
            escolha = input(f"\nSelecione o microfone (1 a {len(mics)}) ou pressione Enter para padrão: ").strip()
            if not escolha:
                return sc.default_microphone()
                
            escolha = int(escolha)
            if 1 <= escolha <= len(mics):
                return mics[escolha - 1]
            print("⚠️ Seleção inválida. Tente novamente.")
        except ValueError:
            print("⚠️ Entrada inválida. Digite um número válido.")


class AudioProcessor:
    """
    Processador de áudio em tempo real para adequação IA.
    Aplica Dithering e Soft Limiter a cada chunk gravado.
    """
    def __init__(self, sample_rate):
        self.sample_rate = sample_rate
        
        # Dither contínuo em nível constante (evita ruído pulsante / estalos de dither)
        self.dither_level = 3e-5

    def process_chunk(self, audio_mic, audio_pc):
        """Processa um chunk de áudio para o streaming em disco."""
        if audio_pc is not None:
            # Canais: [0] = Mic, [1] = PC
            stereo_frame = np.concatenate((audio_mic, audio_pc), axis=1)
        else:
            stereo_frame = audio_mic.copy()

        # Dithering Contínuo: Evita alucinações de IA mantendo o noise floor constante,
        # sem ligar/desligar bruscamente, o que gerava os cliques e "bolhas".
        dither = np.random.normal(0, self.dither_level, stereo_frame.shape).astype(np.float32)
        stereo_frame += dither

        # Soft Limiter
        mask_over = np.abs(stereo_frame) > 0.9
        if np.any(mask_over):
            signs = np.sign(stereo_frame[mask_over])
            excess = np.abs(stereo_frame[mask_over]) - 0.9
            stereo_frame[mask_over] = signs * (0.9 + 0.1 * np.tanh(excess / 0.1))

        return np.clip(stereo_frame, -1.0, 1.0)


class AudioRecorder:
    """
    Orquestrador de Captura e Gravação.
    Resolve problemas de drift de clock lendo dispositivos em threads assíncronas.
    """
    def __init__(self, mic, capturar_pc, file_name, sample_rate=16000):
        self.mic = mic
        self.capturar_pc = capturar_pc
        self.file_name = file_name
        self.sample_rate = sample_rate
        
        self.estado = {'pausado': False, 'encerrado': False}
        self.queue = queue.Queue(maxsize=150) # Buffer para disco
        
        # Filas assíncronas de hardware para evitar overruns por drift de relógio
        self.q_mic = queue.Queue(maxsize=30)
        self.q_pc = queue.Queue(maxsize=30)
        
        self.mic_thread = None
        self.pc_thread = None
        self.process_thread = None
        self.writer_thread = None
        
        self.processor = AudioProcessor(sample_rate)

    def _writer_worker(self):
        """Thread que consome a fila e faz append incremental no arquivo WAV."""
        channels = 2 if self.capturar_pc else 1
        frames_written = 0
        logging.info("Iniciando Thread de Escrita no disco.")
        
        try:
            with sf.SoundFile(self.file_name, mode='w', samplerate=self.sample_rate, channels=channels) as file:
                while not self.estado['encerrado'] or not self.queue.empty():
                    try:
                        chunk = self.queue.get(timeout=0.1)
                        file.write(chunk)
                        frames_written += len(chunk)
                    except queue.Empty:
                        continue
            logging.info(f"Escrita finalizada com sucesso. Total de frames salvos: {frames_written}")
        except Exception as e:
            logging.error(f"Erro na thread de escrita do disco: {e}")
            self.estado['encerrado'] = True

    def _mic_worker(self):
        """Lê o microfone isoladamente."""
        logging.info("Iniciando Thread Isolada de Microfone.")
        try:
            with self.mic.recorder(samplerate=self.sample_rate, channels=1) as stream:
                while not self.estado['encerrado']:
                    data = stream.record(numframes=1024)
                    try: self.q_mic.put_nowait(data)
                    except queue.Full: pass # descarta silenciosamente para não travar hardware
        except Exception as e:
            logging.error(f"Erro na captura de mic: {e}")
            self.estado['encerrado'] = True

    def _pc_worker(self):
        """Lê o PC de forma inteligente, acompanhando mudanças no dispositivo padrão."""
        logging.info("Iniciando Thread Isolada de Loopback (PC).")
        try:
            current_speaker_id = sc.default_speaker().id
            loopback = sc.get_microphone(id=current_speaker_id, include_loopback=True)
            stream = loopback.recorder(samplerate=self.sample_rate, channels=1)
            stream.__enter__()
            
            check_counter = 0
            while not self.estado['encerrado']:
                check_counter += 1
                if check_counter >= 30:  # A cada ~2 segundos (30 * 1024 / 16000)
                    check_counter = 0
                    new_speaker_id = sc.default_speaker().id
                    if new_speaker_id != current_speaker_id:
                        logging.info("Mudança de dispositivo de áudio detectada. Reconectando...")
                        stream.__exit__(None, None, None)
                        
                        current_speaker_id = new_speaker_id
                        loopback = sc.get_microphone(id=current_speaker_id, include_loopback=True)
                        stream = loopback.recorder(samplerate=self.sample_rate, channels=1)
                        stream.__enter__()
                
                try:
                    data = stream.record(numframes=1024)
                    try: self.q_pc.put_nowait(data)
                    except queue.Full: pass
                except Exception as e:
                    logging.warning(f"Erro ao gravar do loopback (tentando reconectar no próximo ciclo): {e}")
                    time.sleep(0.1) # Pausa curta antes de tentar novamente
                    
        except Exception as e:
            logging.error(f"Erro fatal na captura de loopback: {e}")
            self.estado['encerrado'] = True
        finally:
            try:
                stream.__exit__(None, None, None)
            except:
                pass

    def _process_worker(self):
        """Mistura e processa as filas de forma resiliente ao clock drift."""
        logging.info("Iniciando Thread de Processamento Inteligente.")
        while not self.estado['encerrado']:
            try:
                # O processamento aguarda o mic (fonte primária)
                audio_mic = self.q_mic.get(timeout=0.1)
                
                # Soft-sync: se uma fila encher muito rápido (drift), descarta 1 bloco extra
                if self.q_mic.qsize() > 5:
                    try: audio_mic = self.q_mic.get_nowait()
                    except: pass
                
                audio_pc = None
                if self.capturar_pc:
                    try:
                        audio_pc = self.q_pc.get(timeout=0.05)
                        if self.q_pc.qsize() > 5:
                            try: audio_pc = self.q_pc.get_nowait()
                            except: pass
                    except queue.Empty:
                        # Falta de sincronia transitória: preenche com silêncio em vez de engasgar o Mic
                        audio_pc = np.zeros_like(audio_mic)
                
                if not self.estado['pausado']:
                    processed_chunk = self.processor.process_chunk(audio_mic, audio_pc)
                    try:
                        self.queue.put_nowait(processed_chunk)
                    except queue.Full:
                        logging.warning("Fila de disco cheia!")
                        
            except queue.Empty:
                continue

    def start(self):
        logging.info("Iniciando processo de gravação (Multi-Thread)...")
        self.writer_thread = threading.Thread(target=self._writer_worker)
        self.writer_thread.start()
        
        self.process_thread = threading.Thread(target=self._process_worker)
        self.process_thread.start()
        
        self.mic_thread = threading.Thread(target=self._mic_worker)
        self.mic_thread.start()
        
        if self.capturar_pc:
            self.pc_thread = threading.Thread(target=self._pc_worker)
            self.pc_thread.start()

    def stop(self):
        logging.info("Sinalizando parada ao Orquestrador.")
        self.estado['encerrado'] = True
        if self.mic_thread and self.mic_thread.is_alive(): self.mic_thread.join()
        if self.pc_thread and self.pc_thread.is_alive(): self.pc_thread.join()
        if self.process_thread and self.process_thread.is_alive(): self.process_thread.join()
        if self.writer_thread and self.writer_thread.is_alive(): self.writer_thread.join()

    def toggle_pause(self):
        self.estado['pausado'] = not self.estado['pausado']
        logging.info(f"Gravação {'Pausada' if self.estado['pausado'] else 'Retomada'}.")
        return self.estado['pausado']

    def is_running(self):
        return not self.estado['encerrado']


def main():
    # Setup inicial do Logging (salva em arquivo para auditoria do pipeline AI)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        filename='ai_audio_capture.log',
        filemode='a'
    )
    logging.info("=== Nova Sessão de Captura Iniciada ===")
    
    exibir_cabecalho()
    
    # 1. Configurar Áudio do PC
    capturar_pc_input = input("Deseja capturar também o áudio do computador? (S/n): ").strip().lower()
    capturar_pc = capturar_pc_input != 'n'
    
    aplicar_ducking = False
    if capturar_pc:
        aplicar_ducking = True
        if butter is None or filtfilt is None:
            print("\n⚠️ AVISO: A biblioteca 'scipy' não foi encontrada!")
            print("Para usar a redução de eco no pós-processamento, instale o scipy: pip install scipy")
            print("A redução de eco será desativada nesta gravação.\n")
            aplicar_ducking = False
    print()
    
    # 2. Configurar Microfone
    mic = listar_microfones()
    
    # 3. Configurar Arquivo de Saída
    print("\n--- Configuração de Saída ---")
    data_hora = datetime.now().strftime("%d-%m-%Y %H-%M")
    nome_padrao = f"Audio da Reuniao {data_hora}" # Evitando acentos para não gerar bugs no filepath
    nome_input = input(f"Nome do arquivo sem extensão [padrão: '{nome_padrao}']: ").strip()
    nome_arquivo = f"{nome_input if nome_input else nome_padrao}.wav"
    
    aplicar_nr = nr is not None
    if not aplicar_nr:
        print("\n⚠️ AVISO: A biblioteca 'noisereduce' não foi encontrada!")
        print("Para usar a remoção de ruído pós-processamento, instale-a: pip install noisereduce")
        print("A remoção de ruído será desativada nesta gravação.\n")

    exibir_cabecalho()
    print("⚙️   PREPARANDO DISPOSITIVOS...")
    print(f"🎤  Microfone: {mic.name}")
    if capturar_pc:
        print("🔊  Áudio PC:  Ativado (Detecção Inteligente do Dispositivo Padrão)")
        print(f"🧹  Redução Eco:{'Ativada (Pós-processamento)' if aplicar_ducking else 'Desativada'}")
    if aplicar_nr:
        print(f"✨  Limpeza Ruído: Ativada (Pós-processamento)")
    print(f"💾  Arquivo:   {nome_arquivo}")
    print("-" * 60)
    
    # 4. Inicia Orquestrador de Gravação
    recorder = AudioRecorder(mic, capturar_pc, nome_arquivo, sample_rate=TAXA_AMOSTRAGEM)
    recorder.start()
    
    print("▶️   GRAVAÇÃO INICIADA COM SUCESSO")
    print("=" * 60)
    print("  Comandos rápidos (pressione a tecla, não precisa de Enter):")
    print("  [P] : Pausar / Retomar gravação")
    print("  [E] : Encerrar gravação e salvar")
    print("-" * 60)
    print()
    
    inicio_gravacao = time.time()
    tempo_pausado_total = 0
    inicio_pausa = 0
    
    try:
        while recorder.is_running():
            is_paused = recorder.estado['pausado']
            if is_paused:
                duracao = (inicio_pausa - inicio_gravacao) - tempo_pausado_total
                status = "⏸️   PAUSADO  "
            else:
                duracao = (time.time() - inicio_gravacao) - tempo_pausado_total
                dots = ["🔴", "⚪"]
                dot = dots[int(time.time() * 2) % 2]
                status = f"{dot}  GRAVANDO "
                
            minutos = int(duracao // 60)
            segundos = int(duracao % 60)
            
            sys.stdout.write(f"\r  {status} | ⏱️  Tempo: {minutos:02d}:{segundos:02d} | ⌨️  [P] Pausar [E] Encerrar     ")
            sys.stdout.flush()
            
            if msvcrt.kbhit():
                key = msvcrt.getch().decode('utf-8', 'ignore').lower()
                if key == 'p':
                    pausado = recorder.toggle_pause()
                    if pausado:
                        inicio_pausa = time.time()
                    else:
                        tempo_pausado_total += (time.time() - inicio_pausa)
                elif key == 'e':
                    recorder.stop()
            
            time.sleep(0.1)
                
    except KeyboardInterrupt:
        print("\n\n  ⏹️  Interrupção forçada detectada (Ctrl+C).")
        logging.warning("Interrupção forçada via Ctrl+C pelo usuário.")
        recorder.stop()
    
    # 5. Finalização Imediata (Sem atrasos)
    print("\n⏹️   Encerrando a conexão de áudio e limpando fila. Aguarde...")
    recorder.stop()
    
    print("=" * 60)
    print(f"✅  SUCESSO! Arquivo salvo como: {nome_arquivo}")
    
    # Executa o pós-processamento (Ducking e/ou Noise Reduce)
    if (aplicar_ducking or aplicar_nr) and os.path.exists(nome_arquivo):
        print("\n✨  Iniciando Pós-processamento (Aguarde, isso pode levar alguns segundos)...")
        logging.info("Iniciando fase de pós-processamento...")
        try:
            data, rate = sf.read(nome_arquivo)
            
            # 1. Redução de Eco (Ducking Inteligente com Lookahead)
            if aplicar_ducking and len(data.shape) > 1:
                logging.info("Aplicando Redução de Eco (Ducking) via filtfilt...")
                print("🧹  Aplicando Redução de Eco...")
                mic_data = data[:, 0]
                pc_data = data[:, 1]
                
                # Cria envelope da energia do PC com filtro passa-baixa (zero-phase lookahead)
                pc_rectified = np.abs(pc_data)
                nyq = 0.5 * rate
                cutoff = 5.0 # Hz (Envelope de ~200ms de reação)
                b, a = butter(2, cutoff / nyq, btype='low')
                
                pc_envelope = filtfilt(b, a, pc_rectified)
                
                # Máscara de Ducking: ativa quando energia passa do threshold
                threshold = 0.015
                duck_factor = 0.1 # Reduz o volume do mic para 10%
                
                # Transição suave de ganho
                mask = np.clip((pc_envelope - threshold) * 50.0, 0.0, 1.0)
                gain = 1.0 - mask * (1.0 - duck_factor)
                
                # Aplica o ganho no microfone
                data[:, 0] = mic_data * gain

            # 2. Remoção de Ruído
            if aplicar_nr:
                logging.info("Aplicando Remoção de Ruído (noisereduce)...")
                print("✨  Limpando ruídos de fundo do microfone...")
                if len(data.shape) > 1:
                    mic_data = data[:, 0]
                    mic_reduced = nr.reduce_noise(y=mic_data, sr=rate, prop_decrease=0.9)
                    data_clean = np.column_stack((mic_reduced, data[:, 1]))
                else:
                    data_clean = nr.reduce_noise(y=data, sr=rate, prop_decrease=0.9)
            else:
                data_clean = data
                
            # Sobrescreve o arquivo original diretamente para evitar duplicidade
            sf.write(nome_arquivo, data_clean, rate)
            
            print(f"✅  SUCESSO! Áudio finalizado foi salvo em: {nome_arquivo}")
            logging.info(f"Pós-processamento concluído. Arquivo sobrescrito em: {nome_arquivo}")
        except Exception as e:
            print(f"❌  Erro durante o pós-processamento: {e}")
            logging.error(f"Falha no pós-processamento: {e}")

    print("=" * 60)
    logging.info("=== Sessão Encerrada com Sucesso ===")

if __name__ == "__main__":
    main()