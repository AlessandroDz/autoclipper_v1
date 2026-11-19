"""Controle de todas as lives: usado pelo painel e pelo modo terminal.

É a "camada de comando" do motor: o painel nunca mexe nos monitores direto,
só chama os métodos daqui. Isso permite, no futuro, rodar o motor em outro
processo (ou acessar pelo celular) sem mudar o painel.
"""

import logging
import re
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from . import config, lives, sistema
from .monitor import PAUSADA, MonitorLive
from .vertical import FilaVertical

log = logging.getLogger("main")

PADRAO_NOME = re.compile(
    r"^(?P<canal>.+)_(?P<data>\d{4}-\d{2}-\d{2})_(?P<hora>\d{2}-\d{2}-\d{2})_(?P<motivo>[^_]+)\.mp4$"
)


@dataclass
class Clipe:
    caminho: Path  # vertical
    original: Path
    canal: str
    momento: str  # "2026-11-18 21:40:12"
    motivo: str
    score: float | None
    modificado: float


def ler_nome_clipe(nome: str):
    """'canal_2026-11-18_21-40-12_risada.mp4' -> (canal, '2026-11-18 21:40:12', 'risada')."""
    m = PADRAO_NOME.match(nome)
    if not m:
        return None
    return m["canal"], f"{m['data']} {m['hora'].replace('-', ':')}", m["motivo"]


class Gerenciador:
    def __init__(self, links=None):
        """links=None lê a lista salva (lives.json ou config_local.py) e salva as
        mudanças feitas pelo painel; uma lista explícita não é salva (testes)."""
        self.fila = FilaVertical()
        self.detector = None
        self._lock_detector = threading.Lock()
        self._lock_lista = threading.Lock()
        self._salvar_lista = links is None
        # a lista é trocada inteira a cada mudança (nunca alterada no lugar), então
        # quem estiver percorrendo a lista antiga (o painel) não é atrapalhado
        self.monitores: list[MonitorLive] = []
        for url in links if links is not None else lives.carregar_links():
            if not url.strip():
                continue
            try:
                m = MonitorLive(url, self.fila)
            except ValueError as e:
                log.error(str(e))
                continue
            if any(x.canal == m.canal for x in self.monitores):
                log.warning(f"Live repetida ignorada: {url}")
                continue
            self.monitores.append(m)

    # =================================================================
    #  COMANDOS
    # =================================================================
    def _carregar_detector(self):
        with self._lock_detector:
            if self.detector is None:
                log.info("Carregando modelo de áudio (YAMNet)...")
                from .detector import DetectorAudio

                self.detector = DetectorAudio()
        return self.detector

    def monitor(self, canal: str) -> MonitorLive:
        for m in self.monitores:
            if m.canal == canal:
                return m
        raise KeyError(canal)

    def iniciar(self, canal: str):
        m = self.monitor(canal)
        if m.estado == PAUSADA:
            m.retomar()
        else:
            m.iniciar(self._carregar_detector())

    def pausar(self, canal: str):
        self.monitor(canal).pausar()

    def retomar(self, canal: str):
        self.monitor(canal).retomar()

    def finalizar(self, canal: str):
        self.monitor(canal).finalizar()

    def clipar(self, canal: str):
        return self.monitor(canal).clipar_agora()

    # =================================================================
    #  LISTA DE LIVES (editável pelo painel, sem reiniciar)
    # =================================================================
    def adicionar_live(self, url: str, iniciar: bool = False) -> tuple[bool, str]:
        """Coloca uma live nova na lista. Retorna (ok, mensagem)."""
        url = url.strip()
        if not url:
            return False, "Cole o link da live."
        if "://" not in url:
            url = "https://" + url  # "twitch.tv/canal" colado sem o https
        try:
            novo = MonitorLive(url, self.fila)
        except ValueError:
            return False, "Link não reconhecido. Use um link da Twitch ou do YouTube."
        with self._lock_lista:
            if any(m.canal == novo.canal for m in self.monitores):
                return False, f"{novo.canal} já está na lista."
            self.monitores = [*self.monitores, novo]
            self._gravar_lista()
        log.info(f"Live adicionada pelo painel: {url}")
        if iniciar:
            self.iniciar(novo.canal)
        return True, f"{novo.canal} adicionada."

    def remover_live(self, canal: str) -> None:
        """Finaliza a live (clipes pendentes são terminados) e tira da lista."""
        m = self.monitor(canal)
        m.finalizar()
        with self._lock_lista:
            self.monitores = [x for x in self.monitores if x is not m]
            self._gravar_lista()
        log.info(f"Live removida pelo painel: {m.url}")

    def _gravar_lista(self) -> None:
        if self._salvar_lista:
            lives.salvar_links([m.url for m in self.monitores])

    def iniciar_todas(self):
        for m in self.monitores:
            self.iniciar(m.canal)
        log.info(f"{len(self.monitores)} live(s) em monitoramento.")

    def finalizar_todas(self):
        for m in self.monitores:
            m.finalizar()

    def encerrar_tudo(self, progresso=None, espera_fila_s=900, espera_processos_s=15) -> dict:
        """Desliga tudo sem perder clipe e confere que nenhum programa ficou aberto.

        1. finaliza as lives (clipes pendentes são cortados na hora);
        2. espera a fila terminar de gerar os verticais;
        3. confere no Windows os programas abertos pelo Auto-Clipper e força o
           fechamento do que sobrar.
        """
        avisar = progresso or (lambda _msg: None)
        avisar("Finalizando as lives…")
        self.finalizar_todas()

        inicio = time.time()
        while self.fila.tamanho() and time.time() - inicio < espera_fila_s:
            avisar(f"Convertendo {self.fila.tamanho()} clipe(s) para vertical antes de fechar…")
            time.sleep(1)
        fila_restante = self.fila.tamanho()

        avisar("Conferindo se algum programa ficou aberto…")
        pids = sistema.processos_filhos()
        forcados = 0
        if pids is not None:
            limite = time.time() + espera_processos_s
            while pids and time.time() < limite:
                time.sleep(0.5)
                pids = sistema.processos_filhos() or []
            if pids:
                forcados = len(pids)
                sistema.forcar_encerramento(pids)
                time.sleep(1)
                pids = sistema.processos_filhos() or []

        resumo = {
            "fila_restante": fila_restante,
            "processos_abertos": None if pids is None else len(pids),
            "forcados": forcados,
        }
        log.info(f"Encerrar tudo: {resumo}")
        return resumo

    # =================================================================
    #  CONSULTAS (para o painel)
    # =================================================================
    def status(self) -> list[dict]:
        return [
            {
                "canal": m.canal,
                "plataforma": m.plataforma,
                "url": m.url,
                "estado": m.estado,
                "pendentes": m.clipes_pendentes,
                "clipes_sessao": m.clipes_sessao,
                "score": m.ultimo_score,
            }
            for m in self.monitores
        ]

    def _scores(self) -> dict:
        todos = {}
        for m in self.monitores:
            todos.update(m.scores_clipes)
        return todos

    def listar_clipes(self, limite: int = 20) -> list[Clipe]:
        pasta = Path(config.PASTA_VERTICAL)
        if not pasta.exists():
            return []
        scores = self._scores()
        clipes = []
        for arq in pasta.glob("*/*.mp4"):
            info = ler_nome_clipe(arq.name)
            if not info:
                continue
            canal, momento, motivo = info
            try:
                mod = arq.stat().st_mtime
            except OSError:
                continue
            original = Path(config.PASTA_ORIGINAIS) / canal / arq.name
            clipes.append(Clipe(arq, original, canal, momento, motivo, scores.get(arq.name), mod))
        clipes.sort(key=lambda c: c.modificado, reverse=True)
        return clipes[:limite]

    def clipes_hoje(self) -> int:
        hoje = time.strftime("%Y-%m-%d")
        pasta = Path(config.PASTA_VERTICAL)
        if not pasta.exists():
            return 0
        return sum(1 for arq in pasta.glob(f"*/*_{hoje}_*.mp4"))

    def espaco_livre_gb(self) -> float | None:
        pasta = Path(config.PASTA_VERTICAL)
        alvo = pasta if pasta.exists() else Path(pasta.anchor or ".")
        try:
            return shutil.disk_usage(alvo).free / 1024**3
        except OSError:
            return None

    # =================================================================
    #  LIMPEZA DE CLIPES ANTIGOS
    # =================================================================
    def clipes_antigos(self, dias: int) -> list[Path]:
        """Arquivos (vertical e original) com mais de `dias` dias."""
        limite = time.time() - dias * 86400
        arquivos = []
        for pasta in (config.PASTA_VERTICAL, config.PASTA_ORIGINAIS):
            p = Path(pasta)
            if not p.exists():
                continue
            for arq in p.glob("*/*.mp4"):
                try:
                    if arq.stat().st_mtime < limite:
                        arquivos.append(arq)
                except OSError:
                    pass
        return arquivos

    def apagar_clipes_antigos(self, dias: int) -> int:
        apagados = 0
        for arq in self.clipes_antigos(dias):
            try:
                arq.unlink()
                apagados += 1
            except OSError as e:
                log.warning(f"Não consegui apagar {arq}: {e}")
        log.info(f"{apagados} clipe(s) com mais de {dias} dia(s) apagado(s).")
        return apagados
