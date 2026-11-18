"""Auto-clipper v1 - rode com:  python main.py   (Ctrl+C para parar)"""
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

import config
from monitor import MonitorLive


def configurar_log():
    fmt = logging.Formatter("%(asctime)s [%(name)s] %(message)s", "%H:%M:%S")
    raiz = logging.getLogger()
    raiz.setLevel(logging.INFO)
    for h in (logging.StreamHandler(sys.stdout),
              logging.FileHandler("autoclipper.log", encoding="utf-8")):
        h.setFormatter(fmt)
        raiz.addHandler(h)
    for barulhento in ("tensorflow", "absl", "chat_downloader"):
        logging.getLogger(barulhento).setLevel(logging.ERROR)


def recarregar_path_windows():
    """Terminal aberto antes de instalar o ffmpeg não enxerga o PATH novo: relê do registro."""
    if sys.platform != "win32":
        return
    import os
    import winreg

    extras = []
    for raiz, chave in ((winreg.HKEY_LOCAL_MACHINE,
                         r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
                        (winreg.HKEY_CURRENT_USER, r"Environment")):
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

    links = [l for l in config.LINKS_DAS_LIVES if l.strip()]
    if not links:
        log.error("Coloque pelo menos um link em LINKS_DAS_LIVES (config.py).")
        return

    log.info("Carregando modelo de áudio (YAMNet)...")
    from detector import DetectorAudio
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
