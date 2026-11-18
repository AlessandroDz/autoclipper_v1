"""Modo terminal. Rode da raiz do projeto com:  python -m autoclipper   (Ctrl+C para parar)

Para usar o painel no navegador:  python -m autoclipper.painel
"""

from .sistema import silenciar_tensorflow

silenciar_tensorflow()

import logging
import time

from . import config
from .gerenciador import Gerenciador
from .sistema import configurar_log, garantir_ffmpeg


def main():
    configurar_log()
    log = logging.getLogger("main")

    if not garantir_ffmpeg():
        log.error("ffmpeg não encontrado. Instale com:  winget install Gyan.FFmpeg")
        return

    gerenciador = Gerenciador()
    if not gerenciador.monitores:
        log.error(
            f"Nenhuma live configurada. Coloque os links em LINKS_DAS_LIVES "
            f"no arquivo {config.ARQUIVO_CONFIG_LOCAL} (veja o README)."
        )
        return

    gerenciador.iniciar_todas()
    log.info("Ctrl+C para parar.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("Encerrando...")
        gerenciador.finalizar_todas()


if __name__ == "__main__":
    main()
