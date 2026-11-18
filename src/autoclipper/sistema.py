"""Ajustes de sistema compartilhados pelo terminal e pelo painel.

Log com rotação, PATH do ffmpeg e o "Job Object" do Windows que encerra os
programas filhos (streamlink, yt-dlp, ffmpeg) quando o Auto-Clipper fecha.
"""

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


_job_handle = None  # mantido aberto enquanto o programa vive


def encerrar_filhos_ao_fechar() -> bool:
    """Coloca este processo num Job Object do Windows com KILL_ON_JOB_CLOSE.

    Todo programa que ele abrir (streamlink, yt-dlp, ffmpeg) entra no mesmo job.
    Quando o Auto-Clipper fecha - inclusive fechando a janela no X - o Windows
    encerra todos eles juntos, sem deixar captura ou leitura de chat órfã.
    """
    global _job_handle
    if sys.platform != "win32" or _job_handle is not None:
        return _job_handle is not None
    import ctypes
    from ctypes import wintypes

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [(nome, ctypes.c_ulonglong) for nome in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
        )]  # fmt: skip

    class BASIC_LIMIT(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class EXTENDED_LIMIT(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", BASIC_LIMIT),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kill_on_job_close = 0x2000
    extended_limit_information = 9
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateJobObjectW.restype = wintypes.HANDLE
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    k32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
    ]  # fmt: skip
    k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]

    job = k32.CreateJobObjectW(None, None)
    if not job:
        return False
    info = EXTENDED_LIMIT()
    info.BasicLimitInformation.LimitFlags = kill_on_job_close
    ok = k32.SetInformationJobObject(
        job, extended_limit_information, ctypes.byref(info), ctypes.sizeof(info)
    ) and k32.AssignProcessToJobObject(job, k32.GetCurrentProcess())
    if not ok:
        logging.getLogger("main").warning("Não consegui ativar o encerramento automático.")
        k32.CloseHandle(job)
        return False
    _job_handle = job
    return True
