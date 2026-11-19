"""Leitura do chat (Twitch via IRC anônimo, YouTube via yt-dlp)."""

import json
import logging
import shutil
import socket
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

from . import config


def _textos_chat_youtube(linha: str):
    """Extrai o texto das mensagens de uma linha do live_chat.json do yt-dlp."""
    try:
        dados = json.loads(linha)
    except ValueError:
        return []
    acoes = dados.get("replayChatItemAction", {}).get("actions", [])
    textos = []
    for acao in acoes:
        item = acao.get("addChatItemAction", {}).get("item", {})
        msg = item.get("liveChatTextMessageRenderer")
        if not msg:
            continue
        partes = []
        for run in msg.get("message", {}).get("runs", []):
            if "text" in run:
                partes.append(run["text"])
            elif "emoji" in run:  # emoji vem como objeto; usa o próprio caractere ou o atalho
                e = run["emoji"]
                partes.append(
                    e.get("emojiId", "")
                    if len(e.get("emojiId", "")) <= 2
                    else " ".join(e.get("shortcuts", []))
                )
        textos.append("".join(partes))
    return textos


PLATAFORMAS_COM_CHAT = ("twitch", "youtube")


class LeitorChat:
    def __init__(self, plataforma: str, canal: str, url: str, parar: threading.Event):
        self.plataforma = plataforma
        self.canal = canal
        self.url = url
        self.parar = parar
        self.msgs = deque()  # (timestamp, tem_palavra_chave)
        self.lock = threading.Lock()
        self.inicio = time.time()
        self.log = logging.getLogger(canal)

    # ---------------------------------------------------------------
    def iniciar(self):
        if self.plataforma not in PLATAFORMAS_COM_CHAT:
            # Kick: o chat fica atrás de uma proteção anti-robô; a live é
            # monitorada só pelo áudio (o score do chat fica em 0)
            self.log.info("Chat não suportado nesta plataforma: detecção só pelo áudio.")
            return
        threading.Thread(target=self._loop, daemon=True).start()

    def _registrar(self, texto: str):
        t = texto.lower()
        kw = any(p in t for p in config.PALAVRAS_CHAT)
        with self.lock:
            self.msgs.append((time.time(), kw))

    def _loop(self):
        while not self.parar.is_set():
            try:
                if self.plataforma == "twitch":
                    self._twitch()
                else:
                    self._youtube()
            except Exception as e:
                self.log.warning(f"Chat desconectado ({e}). Tentando de novo em 30s.")
            self.parar.wait(30)

    def _twitch(self):
        sock = socket.create_connection(("irc.chat.twitch.tv", 6667), timeout=300)
        sock.send(b"NICK justinfan54321\r\n")
        sock.send(f"JOIN #{self.canal.lower()}\r\n".encode())
        self.log.info("Chat da Twitch conectado.")
        resto = ""
        while not self.parar.is_set():
            dados = sock.recv(4096)
            if not dados:
                raise ConnectionError("conexão fechada")
            resto += dados.decode("utf-8", errors="ignore")
            *linhas, resto = resto.split("\r\n")
            for linha in linhas:
                if linha.startswith("PING"):
                    sock.send(b"PONG :tmi.twitch.tv\r\n")
                elif " PRIVMSG " in linha:
                    self._registrar(linha.split(" PRIVMSG ", 1)[1].split(" :", 1)[-1])
        sock.close()

    def _youtube(self):
        """O yt-dlp grava o chat ao vivo em JSON (um evento por linha).

        O arquivo é lido enquanto cresce.
        """
        pasta = Path(config.PASTA_BUFFER) / self.canal / "chat"
        shutil.rmtree(pasta, ignore_errors=True)
        pasta.mkdir(parents=True, exist_ok=True)
        # fmt: off
        cmd = [sys.executable, "-m", "yt_dlp", "-q", "--no-warnings", "--skip-download",
               "--write-subs", "--sub-langs", "live_chat", "-o", str(pasta / "chat"), self.url]
        # fmt: on
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            arq = None
            for _ in range(60):  # espera o arquivo aparecer (até 60s)
                achados = list(pasta.glob("chat.live_chat.json*"))
                achados = [a for a in achados if "Frag" not in a.name]
                if achados:
                    arq = achados[0]
                    break
                if proc.poll() is not None or self.parar.wait(1):
                    break
            if arq is None:
                raise ConnectionError("yt-dlp não gerou o arquivo de chat")

            self.log.info("Chat do YouTube conectado.")
            with open(arq, encoding="utf-8", errors="ignore") as f:
                resto = ""
                while not self.parar.is_set():
                    pedaco = f.read()
                    if not pedaco:
                        if proc.poll() is not None:
                            raise ConnectionError("yt-dlp encerrou")
                        self.parar.wait(1)
                        continue
                    resto += pedaco
                    *linhas, resto = resto.split("\n")
                    for linha in linhas:
                        for texto in _textos_chat_youtube(linha):
                            self._registrar(texto)
        finally:
            proc.kill()

    # ---------------------------------------------------------------
    def score(self) -> float:
        """0 a 1: quanto o chat está acima do ritmo normal agora."""
        agora = time.time()
        with self.lock:
            while self.msgs and self.msgs[0][0] < agora - 300:
                self.msgs.popleft()
            total = len(self.msgs)
            recentes = [m for m in self.msgs if m[0] >= agora - 10]

        if total < 20:  # pouco histórico ainda
            return 0.0
        janela_base = min(300, max(agora - self.inicio, 10))
        taxa_base = total / janela_base
        taxa_agora = len(recentes) / 10
        razao = taxa_agora / max(taxa_base, 0.1)
        s = min(max((razao - 1.5) / 2.5, 0.0), 1.0)  # 1.5x = 0 | 4x = 1

        if len(recentes) >= 5:
            frac_kw = sum(kw for _, kw in recentes) / len(recentes)
            if frac_kw >= 0.3:
                s = min(1.0, s + 0.3)
        return s
