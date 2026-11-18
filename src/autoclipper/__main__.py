"""Ponto de entrada. Rode da raiz do projeto com:  python -m autoclipper   (Ctrl+C para parar)"""

import os
import warnings

# silencia os avisos do TensorFlow / tensorflow-hub (não afetam o funcionamento)
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
os.environ.setdefault("TF_ENABLE_ONEDNN_OPTS", "0")
warnings.filterwarnings("ignore", message="pkg_resources is deprecated")

import logging
import shutil
import sys
import time
from logging.handlers import RotatingFileHandler

from . import config
from .monitor import MonitorLive


def configurar_log():
    raiz = logging.getLogger()
    raiz.setLevel(logging.INFO)

    tela = logging.StreamHandler(sys.stdout)
    tela.setFormatter(logging.Formatter("%(asctime)s [%(name)s] %(message)s", "%H:%M:%S"))

    # arquivo com rotação: ao chegar em LOG_MAX_MB, vira .1, .2... e o mais antigo é apagado
    arquivo = RotatingFileHandler(
        "autoclipper.log",
        maxBytes=config.LOG_MAX_MB * 1024 * 1024,
        backupCount=config.LOG_BACKUPS,
        encoding="utf-8",
    )
    arquivo.setFormatter(
        logging.Formatter("%(asctime)s [%(name)s] %(message)s", "%Y-%m-%d %H:%M:%S")
    )

    raiz.addHandler(tela)
    raiz.addHandler(arquivo)
    for barulhento in ("tensorflow", "absl"):
        logging.getLogger(barulhento).setLevel(logging.ERROR)


def recarregar_path_windows():
    """Terminal aberto antes de instalar o ffmpeg não enxerga o PATH novo: relê do registro."""
    if sys.platform != "win32":
        return
    import winreg

    extras = []
    for raiz, chave in (
        (
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
        ),
        (winreg.HKEY_CURRENT_USER, r"Environment"),
    ):
        try:
            with winreg.OpenKey(raiz, chave) as k:
                extras.append(os.path.expandvars(winreg.QueryValueEx(k, "Path")[0]))
        except OSError:
            pass
    os.environ["PATH"] = os.pathsep.join([os.environ.get("PATH", "")] + extras)


def main():
    configurar_log()
    log = logging.getLogger("main")

    if not shutil.which("ffmpeg"):
        recarregar_path_windows()
    if not shutil.which("ffmpeg"):
        log.error("ffmpeg não encontrado. Instale com:  winget install Gyan.FFmpeg")
        return

    links = [link for link in config.LINKS_DAS_LIVES if link.strip()]
    if not links:
        log.error(
            f"Nenhuma live configurada. Coloque os links em LINKS_DAS_LIVES "
            f"no arquivo {config.ARQUIVO_CONFIG_LOCAL} (veja o README)."
        )
        return

    log.info("Carregando modelo de áudio (YAMNet)...")
    from .detector import DetectorAudio

    detector = DetectorAudio()

    monitores = [MonitorLive(url, detector) for url in links]
    for m in monitores:
        m.iniciar()
    log.info(f"{len(monitores)} live(s) em monitoramento. Ctrl+C para parar.")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("Encerrando...")
        for m in monitores:
            m.parar()


if __name__ == "__main__":
    main()
