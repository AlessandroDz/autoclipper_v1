"""Ajustes de sistema compartilhados pelo terminal e pelo painel: log e PATH do ffmpeg."""

import logging
import os
import shutil
import sys
import warnings
from logging.handlers import RotatingFileHandler

from . import config

FORMATO = "%(asctime)s [%(name)s] %(message)s"


def silenciar_tensorflow():
    """Avisos do TensorFlow / tensorflow-hub não afetam o funcionamento."""
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
    os.environ.setdefault("TF_ENABLE_ONEDNN_OPTS", "0")
    warnings.filterwarnings("ignore", message="pkg_resources is deprecated")


def configurar_log(no_terminal: bool = True):
    raiz = logging.getLogger()
    if getattr(raiz, "_autoclipper_configurado", False):
        return
    raiz.setLevel(logging.INFO)

    # arquivo com rotação: ao chegar em LOG_MAX_MB, vira .1, .2... e o mais antigo é apagado
    arquivo = RotatingFileHandler(
        "autoclipper.log",
        maxBytes=config.LOG_MAX_MB * 1024 * 1024,
        backupCount=config.LOG_BACKUPS,
        encoding="utf-8",
    )
    arquivo.setFormatter(logging.Formatter(FORMATO, "%Y-%m-%d %H:%M:%S"))
    raiz.addHandler(arquivo)

    if no_terminal:
        tela = logging.StreamHandler(sys.stdout)
        tela.setFormatter(logging.Formatter(FORMATO, "%H:%M:%S"))
        raiz.addHandler(tela)

    for barulhento in ("tensorflow", "absl"):
        logging.getLogger(barulhento).setLevel(logging.ERROR)
    raiz._autoclipper_configurado = True


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


def garantir_ffmpeg() -> bool:
    if not shutil.which("ffmpeg"):
        recarregar_path_windows()
    return shutil.which("ffmpeg") is not None
