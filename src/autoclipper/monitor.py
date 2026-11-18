"""Monitor de uma live: captura -> buffer -> detecção -> clipe.

Ciclo de vida (controlado pelo painel ou pelo terminal):
    iniciar()  -> limpa o buffer e começa a capturar e detectar
    pausar()   -> para captura, análise e chat (zero CPU e banda); o buffer fica
    retomar()  -> volta a capturar; clipes nunca juntam trechos de antes da pausa
    finalizar()-> para tudo e apaga o buffer
    clipar_agora() -> clipe manual (1 min antes + 2 min depois do clique)
"""

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
from .vertical import Trabalho

TAXA = 16000  # Hz do áudio de análise
BYTES_POR_SEG = TAXA * 2  # int16 mono
FORMATO_SEG = "seg_%Y%m%d_%H%M%S"

# estados possíveis (o painel mostra cada um com uma cor)
PARADA, CONECTANDO, AO_VIVO, OFFLINE, PAUSADA = (
    "parada",
    "conectando",
    "ao_vivo",
    "offline",
    "pausada",
)


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


def nome_do_clipe(canal: str, t: float, motivo: str) -> str:
    data = time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime(t))
    return f"{canal}_{data}_{motivo}.mp4"


class MonitorLive:
    def __init__(self, url: str, fila, detector=None):
        self.url = url.strip()
        self.plataforma, self.canal = identificar_live(self.url)
        self.fila = fila
        self.detector = detector
        self.log = logging.getLogger(self.canal)

        self.pasta_buffer = Path(config.PASTA_BUFFER) / self.canal
        self.pasta_processando = Path(config.PASTA_BUFFER) / "_processando"

        self.estado = PARADA
        self.evento: threading.Event | None = None  # um por sessão de captura
        self.chat: LeitorChat | None = None
        self.procs = []
        self._lock = threading.Lock()

        self.clipes_sessao = 0  # clipes gerados desde que o programa abriu
        self.clipes_pendentes = 0  # clipes aguardando os 2 min ou na fila
        # ao finalizar, os clipes que ainda aguardam os 2 min são cortados na hora
        # (com o que já foi gravado) antes de o buffer ser apagado
        self._cortar_agora = threading.Event()
        self._threads_clipe: list[threading.Thread] = []
        self.ultimo_score = 0.0
        self.scores_clipes: dict[str, float] = {}  # nome do arquivo -> score

        self._zerar_deteccao()

    def _zerar_deteccao(self):
        self.audio = bytearray()
        self.audio_lock = threading.Lock()
        self.ultimo_audio = 0.0
        self.inicio_sessao = time.time()
        self.online = False
        self.hist_db = deque(maxlen=120)  # 2 min de volume
        self.janela = deque(maxlen=10)  # últimos 10s (dicts com os detalhes de cada segundo)
        self.hist_score = deque(maxlen=config.BUFFER_MINUTOS * 60)  # (t, score, motivo)
        self.fim_ultimo_clipe = getattr(self, "fim_ultimo_clipe", 0.0)
        self.ultimo_corte = time.time()
        self._calib = None
        self._calib_t = 0.0

    # =================================================================
    #  CONTROLE
    # =================================================================
    @property
    def rodando(self) -> bool:
        return self.estado in (CONECTANDO, AO_VIVO, OFFLINE)

    def iniciar(self, detector=None):
        """Começa do zero (limpa o buffer)."""
        with self._lock:
            if self.rodando:
                return
            if detector is not None:
                self.detector = detector
            shutil.rmtree(self.pasta_buffer, ignore_errors=True)
            self.log.info(f"Monitorando {self.plataforma}: {self.url}")
            self._comecar()

    def retomar(self):
        """Volta de uma pausa (mantém o buffer)."""
        with self._lock:
            if self.estado != PAUSADA:
                return
            self.log.info("Retomando.")
            self._comecar()

    def pausar(self):
        with self._lock:
            if not self.rodando:
                return
            self._parar()
            self.estado = PAUSADA
            self.log.info("Pausada (captura, análise e chat desligados).")

    def finalizar(self):
        with self._lock:
            if self.estado == PARADA:
                return
            self._parar()
            self.estado = PARADA
            self._cortar_pendentes()
            shutil.rmtree(self.pasta_buffer, ignore_errors=True)
            self.log.info("Finalizada.")

    def _cortar_pendentes(self):
        """Corta já os clipes que aguardavam os 2 min, para não perder o momento."""
        pendentes = [t for t in self._threads_clipe if t.is_alive()]
        if pendentes:
            self.log.info(f"Cortando {len(pendentes)} clipe(s) pendente(s) antes de finalizar...")
            self._cortar_agora.set()
            for t in pendentes:
                t.join(timeout=120)
        self._threads_clipe = []
        self._cortar_agora = threading.Event()

    def clipar_agora(self) -> tuple[bool, str]:
        """Clipe manual: sempre gera, mesmo com outro clipe em andamento."""
        if self.estado != AO_VIVO:
            return False, "a live precisa estar ao vivo para clipar"
        t = time.time()
        self._disparar(t, "manual", None)
        return True, "clipe manual iniciado - fica pronto em ~2 min"

    def _comecar(self):
        if self.detector is None:
            raise RuntimeError("detector de áudio não carregado")
        self.pasta_buffer.mkdir(parents=True, exist_ok=True)
        self.pasta_processando.mkdir(parents=True, exist_ok=True)
        self._zerar_deteccao()
        self.estado = CONECTANDO
        self.evento = evento = threading.Event()
        for alvo in (self._loop_captura, self._loop_analise, self._loop_limpeza):
            threading.Thread(target=alvo, args=(evento,), daemon=True).start()
        self.chat = LeitorChat(self.plataforma, self.canal, self.url, evento)
        self.chat.iniciar()

    def _parar(self):
        if self.evento:
            self.evento.set()
        self._matar_processos()
        self.online = False

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

    def _loop_captura(self, evento):
        # log de erros do streamlink/ffmpeg: escrito direto pelos processos, então a
        # rotação é feita ao abrir (passou do limite -> vira .1, substituindo o antigo)
        caminho_log = self.pasta_buffer.parent / f"{self.canal}_captura.log"
        if caminho_log.exists() and caminho_log.stat().st_size > config.LOG_MAX_MB * 1024 * 1024:
            caminho_log.replace(caminho_log.with_name(caminho_log.name + ".1"))
        with open(caminho_log, "ab") as log_erros:
            while not evento.is_set():
                try:
                    self._capturar(evento, log_erros)
                except FileNotFoundError as e:
                    self.log.error(f"Programa não encontrado: {e}. Confira a instalação do ffmpeg.")
                finally:
                    self._matar_processos()
                    self.online = False

                if not evento.is_set():
                    self.estado = OFFLINE
                    self.log.info("Live offline/caiu. Tentando de novo em 30s...")
                    evento.wait(30)

    def _capturar(self, evento, log_erros):
        """Uma conexão: roda até a live cair ou a sessão ser parada."""
        p1 = subprocess.Popen(self._comando_captura(), stdout=subprocess.PIPE, stderr=log_erros)
        p2 = subprocess.Popen(
            self._comando_ffmpeg(), stdin=p1.stdout, stdout=subprocess.PIPE, stderr=log_erros
        )
        p1.stdout.close()
        self.procs = [p1, p2]
        avisou = False

        while not evento.is_set():
            dados = p2.stdout.read(3200)  # 0,1 s de áudio
            if not dados:
                break
            agora = time.time()
            if not avisou:
                self.log.info("Live ONLINE - capturando.")
                avisou, self.online = True, True
                self.estado = AO_VIVO
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
    def _loop_analise(self, evento):
        while not evento.wait(1.0):
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
        self.janela.append(
            {
                "t": agora,
                "pts": pts_audio,
                "motivo": motivo,
                "tipo": tipo,
                "evento": evento,
                "vol": vol,
                "db": db,
                "base": base,
                "musica": musica,
            }
        )

        # --- combina com o chat (o chat reage alguns segundos depois)
        pico = max(self.janela, key=lambda j: j["pts"])
        chat = self.chat.score() if self.chat else 0.0
        score = pico["pts"] + config.PESO_CHAT * chat
        self.ultimo_score = score
        self.hist_score.append((pico["t"], score, pico["motivo"]))
        self._log_calibracao(agora, score, pico, chat)

        # --- disparo normal
        if score >= config.LIMIAR_SCORE and pico["t"] >= self.fim_ultimo_clipe:
            self._disparar(pico["t"], pico["motivo"], score)
            return

        # --- corte por tempo: muito tempo sem clipe, corta o melhor momento do período
        if agora - self.ultimo_corte >= config.CORTE_FORCADO_MINUTOS * 60:
            minimo = max(
                self.fim_ultimo_clipe + config.SEGUNDOS_ANTES,
                self.inicio_sessao + config.SEGUNDOS_ANTES,
            )
            candidatos = [h for h in self.hist_score if h[0] >= minimo]
            if candidatos:
                t, s, _ = max(candidatos, key=lambda h: h[1])
                self._disparar(t, config.MOTIVO_POR_TEMPO, s)
            else:
                self.ultimo_corte = agora

    def _log_calibracao(self, agora, score, pico, chat):
        """A cada INTERVALO_LOG_SCORE s, loga o maior score e o que pesou nele."""
        if not config.INTERVALO_LOG_SCORE:
            return
        if self._calib is None or score >= self._calib[0]:
            self._calib = (score, pico, chat)
        if agora - self._calib_t >= config.INTERVALO_LOG_SCORE:
            s, p, ch = self._calib
            base = f"{p['base']:.1f}" if p["base"] is not None else "--"
            self.log.info(
                f"[calib] max={s:.2f} | {p['tipo']}={p['evento']:.2f} vol={p['vol']:.2f} "
                f"(db={p['db']:.1f} base={base}) musica={p['musica']:.2f} chat={ch:.2f}"
            )
            self._calib_t, self._calib = agora, None

    def _disparar(self, t, motivo, score):
        self.fim_ultimo_clipe = max(self.fim_ultimo_clipe, t + config.SEGUNDOS_DEPOIS)
        self.ultimo_corte = time.time()
        self.clipes_pendentes += 1
        hora = time.strftime("%H:%M:%S", time.localtime(t))
        score_txt = f"{score:.2f}" if score is not None else "-"
        self.log.info(f"FLAG! motivo={motivo} score={score_txt} momento={hora} - gerando clipe...")
        thread = threading.Thread(
            target=self._gerar_clipe,
            args=(t, motivo, score, self.inicio_sessao, self._cortar_agora),
            daemon=True,
        )
        self._threads_clipe = [th for th in self._threads_clipe if th.is_alive()] + [thread]
        thread.start()

    # =================================================================
    #  CLIPE (corte 16:9 sem recodificar -> fila do vertical)
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

    def selecionar_segmentos(self, segs, ini, fim, inicio_sessao):
        """Pedaços que cobrem [ini, fim], só desta sessão (nunca de antes de uma pausa)."""
        segs = [(s, a) for s, a in segs if s >= inicio_sessao - 2]
        selecionados = []
        for i, (s, arq) in enumerate(segs):
            e = segs[i + 1][0] if i + 1 < len(segs) else s + config.DURACAO_SEGMENTO
            if e > ini and s < fim:
                selecionados.append((s, arq))
        return selecionados

    def _gerar_clipe(self, t, motivo, score, inicio_sessao, cortar_agora):
        try:
            ok = self._cortar_original(t, motivo, score, inicio_sessao, cortar_agora)
        except Exception as e:
            self.log.error(f"Falha ao gerar clipe: {e}")
            ok = False
        if not ok:
            self.clipes_pendentes = max(0, self.clipes_pendentes - 1)

    def _cortar_original(self, t, motivo, score, inicio_sessao, cortar_agora) -> bool:
        ini = t - config.SEGUNDOS_ANTES
        fim = t + config.SEGUNDOS_DEPOIS

        # espera os 2 minutos posteriores serem gravados; se a live for finalizada
        # antes disso, corta na hora com o que já foi gravado (o clipe sai mais curto)
        espera = fim + config.DURACAO_SEGMENTO + 5 - time.time()
        if espera > 0:
            cortar_agora.wait(espera)

        selecionados = self.selecionar_segmentos(self._listar_segmentos(), ini, fim, inicio_sessao)
        if not selecionados:
            self.log.warning("Nenhum trecho no buffer para esse momento - clipe cancelado.")
            return False

        offset = max(0.0, ini - selecionados[0][0])
        duracao = fim - max(ini, selecionados[0][0])

        nome = nome_do_clipe(self.canal, t, motivo)
        self.pasta_processando.mkdir(parents=True, exist_ok=True)
        lista = self.pasta_processando / f"lista_{nome}.txt"
        temp = self.pasta_processando / f"orig_{nome}"

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
            return False

        if score is not None:
            self.scores_clipes[nome] = score
        self.fila.adicionar(Trabalho(self.canal, nome, temp, ao_terminar=self._clipe_pronto))
        self.log.info(f"Clipe cortado, na fila do vertical: {nome}")
        return True

    def _clipe_pronto(self, trabalho, ok):
        self.clipes_pendentes = max(0, self.clipes_pendentes - 1)
        self.clipes_sessao += 1

    # =================================================================
    #  LIMPEZA DO BUFFER
    # =================================================================
    def _loop_limpeza(self, evento):
        while not evento.wait(30):
            limite = time.time() - config.BUFFER_MINUTOS * 60
            for inicio, arq in self._listar_segmentos():
                if inicio < limite:
                    try:
                        os.remove(arq)
                    except OSError:
                        pass
