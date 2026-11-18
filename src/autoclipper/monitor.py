"""Monitor de uma live: captura -> buffer -> detecção -> clipe."""

import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np

from . import config
from .chat import LeitorChat
from .detector import rms_db

TAXA = 16000  # Hz do áudio de análise
BYTES_POR_SEG = TAXA * 2  # int16 mono
FORMATO_SEG = "seg_%Y%m%d_%H%M%S"


def identificar_live(url: str):
    """Retorna (plataforma, nome_canal) a partir do link."""
    u = urlparse(url.strip())
    host = u.netloc.lower()
    partes = [p for p in u.path.split("/") if p]
    nome = None
    if "twitch.tv" in host and partes:
        return "twitch", partes[0].lower()
    if "youtube.com" in host or "youtu.be" in host:
        if partes and partes[0].startswith("@"):
            nome = partes[0][1:]
        elif "v" in parse_qs(u.query):
            nome = parse_qs(u.query)["v"][0]
        elif len(partes) > 1 and partes[0] in ("channel", "c", "user", "live"):
            nome = partes[1]
        elif "youtu.be" in host and partes:
            nome = partes[0]
        if nome:
            return "youtube", re.sub(r"[^\w\-]", "_", nome)
    raise ValueError(f"Link não reconhecido: {url}")


class MonitorLive:
    def __init__(self, url: str, detector):
        self.url = url.strip()
        self.plataforma, self.canal = identificar_live(self.url)
        self.detector = detector
        self.log = logging.getLogger(self.canal)

        self.pasta_buffer = Path(config.PASTA_BUFFER) / self.canal
        self.pasta_clipes = Path(config.PASTA_CLIPES) / self.canal

        self.parar_evento = threading.Event()
        self.chat = LeitorChat(self.plataforma, self.canal, self.url, self.parar_evento)
        self.procs = []

        # áudio
        self.audio = bytearray()
        self.audio_lock = threading.Lock()
        self.ultimo_audio = 0.0
        self.inicio_buffer = None
        self.online = False

        # detecção
        self.hist_db = deque(maxlen=120)  # 2 min de volume
        self.janela = deque(maxlen=10)  # últimos 10s
        self.hist_score = deque(maxlen=config.BUFFER_MINUTOS * 60)  # (t, score, motivo)
        self.fim_ultimo_clipe = 0.0
        self.ultimo_corte = time.time()

    # =================================================================
    def iniciar(self):
        if self.pasta_buffer.exists():
            shutil.rmtree(self.pasta_buffer, ignore_errors=True)
        self.pasta_buffer.mkdir(parents=True, exist_ok=True)
        self.pasta_clipes.mkdir(parents=True, exist_ok=True)

        self.log.info(f"Monitorando {self.plataforma}: {self.url}")
        for alvo in (self._loop_captura, self._loop_analise, self._loop_limpeza):
            threading.Thread(target=alvo, daemon=True).start()
        self.chat.iniciar()

    def parar(self):
        self.parar_evento.set()
        self._matar_processos()
        self.log.info("Parado.")

    # =================================================================
    #  CAPTURA
    # =================================================================
    # Listas de argumentos de linha de comando: o formatador fica desligado para
    # manter cada opção na mesma linha do seu valor (ex.: "-f", "segment").
    # fmt: off
    def _comando_captura(self):
        if self.plataforma == "youtube" and config.USAR_YTDLP_NO_YOUTUBE:
            return [sys.executable, "-m", "yt_dlp", "-q", "--no-warnings", "-f", "best",
                    "--hls-use-mpegts", "-o", "-", self.url]
        return [sys.executable, "-m", "streamlink", "--stdout", "--loglevel", "error",
                self.url, config.QUALIDADE]

    def _comando_ffmpeg(self):
        padrao = str(self.pasta_buffer / f"{FORMATO_SEG}.ts")
        return [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
            # saída 1: pedaços de vídeo+áudio sem recodificar (buffer)
            "-map", "0:v:0?", "-map", "0:a:0?", "-c", "copy",
            "-f", "segment", "-segment_time", str(config.DURACAO_SEGMENTO),
            "-segment_format", "mpegts", "-reset_timestamps", "1", "-strftime", "1", padrao,
            # saída 2: áudio cru 16 kHz mono para análise
            "-map", "0:a:0", "-ac", "1", "-ar", str(TAXA), "-f", "s16le", "pipe:1",
        ]
    # fmt: on

    def _loop_captura(self):
        # log de erros do streamlink/ffmpeg: escrito direto pelos processos, então a
        # rotação é feita ao abrir (passou do limite -> vira .1, substituindo o antigo)
        caminho_log = self.pasta_buffer.parent / f"{self.canal}_captura.log"
        if caminho_log.exists() and caminho_log.stat().st_size > config.LOG_MAX_MB * 1024 * 1024:
            caminho_log.replace(caminho_log.with_name(caminho_log.name + ".1"))
        with open(caminho_log, "ab") as log_erros:
            while not self.parar_evento.is_set():
                try:
                    self._capturar(log_erros)
                except FileNotFoundError as e:
                    self.log.error(f"Programa não encontrado: {e}. Confira a instalação do ffmpeg.")
                finally:
                    self._matar_processos()
                    self.online = False

                if not self.parar_evento.is_set():
                    self.log.info("Live offline/caiu. Tentando de novo em 30s...")
                    self.parar_evento.wait(30)

    def _capturar(self, log_erros):
        """Uma sessão de captura: roda até a live cair ou o monitor ser parado."""
        p1 = subprocess.Popen(self._comando_captura(), stdout=subprocess.PIPE, stderr=log_erros)
        p2 = subprocess.Popen(
            self._comando_ffmpeg(), stdin=p1.stdout, stdout=subprocess.PIPE, stderr=log_erros
        )
        p1.stdout.close()
        self.procs = [p1, p2]
        avisou = False

        while not self.parar_evento.is_set():
            dados = p2.stdout.read(3200)  # 0,1 s de áudio
            if not dados:
                break
            agora = time.time()
            if not avisou:
                self.log.info("Live ONLINE - capturando.")
                avisou, self.online = True, True
                if self.inicio_buffer is None:
                    self.inicio_buffer = agora
            with self.audio_lock:
                self.audio.extend(dados)
                excesso = len(self.audio) - 5 * BYTES_POR_SEG
                if excesso > 0:
                    del self.audio[: excesso - (excesso % 2)]
            self.ultimo_audio = agora

    def _matar_processos(self):
        for p in self.procs:
            try:
                p.kill()
            except Exception:
                pass
        self.procs = []

    # =================================================================
    #  ANÁLISE (1x por segundo)
    # =================================================================
    def _loop_analise(self):
        while not self.parar_evento.wait(1.0):
            agora = time.time()

            # live travou sem fechar? reinicia a captura
            if self.online and agora - self.ultimo_audio > 60:
                self.log.warning("Sem áudio há 60s - reiniciando captura.")
                self._matar_processos()
                continue

            with self.audio_lock:
                bruto = bytes(self.audio[-2 * BYTES_POR_SEG :])
            if not self.online or len(bruto) < BYTES_POR_SEG:
                continue

            x = np.frombuffer(bruto, dtype=np.int16).astype(np.float32) / 32768.0
            try:
                self._avaliar(agora, x)
            except Exception as e:
                self.log.error(f"Erro na análise: {e}")

    def _avaliar(self, agora, x):
        # --- volume relativo à média do streamer
        db = rms_db(x[-TAXA:])
        self.hist_db.append(db)
        base = float(np.median(self.hist_db)) if len(self.hist_db) >= 30 else None

        # --- YAMNet
        grupos, musica = self.detector.analisar(x)
        tipo, evento = max(grupos.items(), key=lambda kv: kv[1])

        if musica > config.LIMIAR_MUSICA and musica >= evento:
            evento *= 0.3  # música dominando: derruba o evento
            vol = 0.0  # e ignora volume
        elif base is not None:
            faixa = config.DB_ACIMA_MEDIA_MAX - config.DB_ACIMA_MEDIA_MIN
            vol = min(max((db - base - config.DB_ACIMA_MEDIA_MIN) / faixa, 0.0), 1.0)
        else:
            vol = 0.0

        pts_audio = config.PESO_AUDIO * evento + config.PESO_VOLUME * vol
        motivo = tipo if evento >= 0.3 else ("volume" if vol >= 0.5 else "chat")
        self.janela.append((agora, pts_audio, motivo))

        # --- combina com o chat (o chat reage alguns segundos depois)
        t_pico, pts_pico, motivo_pico = max(self.janela, key=lambda j: j[1])
        score = pts_pico + config.PESO_CHAT * self.chat.score()
        self.hist_score.append((t_pico, score, motivo_pico))

        # --- log de calibração: maior score a cada INTERVALO_LOG_SCORE segundos
        if config.INTERVALO_LOG_SCORE:
            atual = (score, tipo, evento, vol, db, base, musica, self.chat.score())
            if score >= getattr(self, "_calib_max", (-1,))[0]:
                self._calib_max = atual
            if agora - getattr(self, "_calib_t", 0) >= config.INTERVALO_LOG_SCORE:
                s, tp, ev, vl, d, b, mu, ch = self._calib_max
                b_txt = f"{b:.1f}" if b is not None else "--"
                self.log.info(
                    f"[calib] max={s:.2f} | {tp}={ev:.2f} vol={vl:.2f} "
                    f"(db={d:.1f} base={b_txt}) musica={mu:.2f} chat={ch:.2f}"
                )
                self._calib_t, self._calib_max = agora, (-1,)

        # --- disparo normal
        if score >= config.LIMIAR_SCORE and t_pico >= self.fim_ultimo_clipe:
            self._disparar(t_pico, motivo_pico, score)
            return

        # --- corte forçado
        if agora - self.ultimo_corte >= config.CORTE_FORCADO_MINUTOS * 60:
            minimo = max(
                self.fim_ultimo_clipe + config.SEGUNDOS_ANTES,
                (self.inicio_buffer or agora) + config.SEGUNDOS_ANTES,
            )
            candidatos = [h for h in self.hist_score if h[0] >= minimo]
            if candidatos:
                t, s, _ = max(candidatos, key=lambda h: h[1])
                self._disparar(t, config.MOTIVO_POR_TEMPO, s)
            else:
                self.ultimo_corte = agora

    def _disparar(self, t, motivo, score):
        self.fim_ultimo_clipe = t + config.SEGUNDOS_DEPOIS
        self.ultimo_corte = time.time()
        hora = time.strftime("%H:%M:%S", time.localtime(t))
        self.log.info(f"FLAG! motivo={motivo} score={score:.2f} momento={hora} - gerando clipe...")
        threading.Thread(target=self._gerar_clipe, args=(t, motivo), daemon=True).start()

    # =================================================================
    #  CLIPE
    # =================================================================
    def _listar_segmentos(self):
        segs = []
        for arq in self.pasta_buffer.glob("seg_*.ts"):
            try:
                inicio = time.mktime(time.strptime(arq.stem, FORMATO_SEG))
                segs.append((inicio, arq))
            except ValueError:
                pass
        return sorted(segs)

    def _gerar_clipe(self, t, motivo):
        ini = t - config.SEGUNDOS_ANTES
        fim = t + config.SEGUNDOS_DEPOIS

        # espera os 2 minutos posteriores serem gravados
        espera = fim + config.DURACAO_SEGMENTO + 5 - time.time()
        if espera > 0:
            self.parar_evento.wait(espera)

        segs = self._listar_segmentos()
        selecionados = []
        for i, (s, arq) in enumerate(segs):
            e = segs[i + 1][0] if i + 1 < len(segs) else s + config.DURACAO_SEGMENTO
            if e > ini and s < fim:
                selecionados.append((s, arq))
        if not selecionados:
            self.log.warning("Nenhum trecho no buffer para esse momento - clipe cancelado.")
            return

        offset = max(0.0, ini - selecionados[0][0])
        duracao = fim - max(ini, selecionados[0][0])

        data = time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime(t))
        nome = f"{self.canal}_{data}_{motivo}.mp4"
        lista = self.pasta_buffer / f"lista_{data}.txt"
        temp = self.pasta_buffer / f"temp_{nome}"
        destino = self.pasta_clipes / nome

        lista.write_text(
            "".join(f"file '{arq.resolve().as_posix()}'\n" for _, arq in selecionados),
            encoding="utf-8",
        )
        # fmt: off
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-ss", f"{offset:.2f}", "-i", str(lista),
            "-t", f"{duracao:.2f}", "-c", "copy",
            "-bsf:a", "aac_adtstoasc", "-movflags", "+faststart", str(temp),
        ]
        # fmt: on
        r = subprocess.run(cmd, capture_output=True, text=True)
        lista.unlink(missing_ok=True)

        if r.returncode != 0 or not temp.exists():
            self.log.error(f"Falha ao gerar clipe: {r.stderr.strip()[:300]}")
            return
        # gera fora do Drive e só depois move (o Drive não sincroniza arquivo pela metade)
        shutil.move(str(temp), str(destino))
        self.log.info(f"CLIPE SALVO: {destino}")

    # =================================================================
    #  LIMPEZA DO BUFFER
    # =================================================================
    def _loop_limpeza(self):
        while not self.parar_evento.wait(30):
            limite = time.time() - config.BUFFER_MINUTOS * 60
            for inicio, arq in self._listar_segmentos():
                if inicio < limite:
                    try:
                        os.remove(arq)
                    except OSError:
                        pass
