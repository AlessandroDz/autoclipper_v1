# =====================================================================
#                    CONFIGURAÇÃO DO AUTO-CLIPPER (v1)
#
#  Valores padrão. NÃO edite aqui: crie um config_local.py na pasta de
#  onde você roda o programa (a raiz do projeto) com seus links e pastas.
#  Qualquer valor definido lá substitui o daqui (ver o fim do arquivo).
# =====================================================================
import importlib.util
from pathlib import Path

# Pasta de onde o programa é executado (raiz do projeto)
PASTA_BASE = Path.cwd()

# ---------------------------------------------------------------------
#  >>> LINKS DAS LIVES <<<   (Twitch ou YouTube) - defina no config_local.py
#  Ex.: ["https://www.twitch.tv/CANAL", "https://www.youtube.com/live/ID_DO_VIDEO"]
# ---------------------------------------------------------------------
LINKS_DAS_LIVES: list[str] = []

# ---------------------------------------------------------------------
#  PASTAS
# ---------------------------------------------------------------------
# Onde os clipes finais são salvos (padrão: pasta "videos" na raiz do projeto).
# Para acessar pelo celular, aponte para o Google Drive para desktop,
# ex.: r"G:\Meu Drive\Clipes"
PASTA_CLIPES = str(PASTA_BASE / "videos")

# Buffer temporário (pedaços de 10s das lives). NÃO coloque dentro do Drive.
PASTA_BUFFER = str(PASTA_BASE / "buffer")

# ---------------------------------------------------------------------
#  CLIPE
# ---------------------------------------------------------------------
SEGUNDOS_ANTES = 60  # 1 min antes da flag
SEGUNDOS_DEPOIS = 120  # 2 min depois da flag
DURACAO_SEGMENTO = 10  # tamanho de cada pedaço do buffer (s)
BUFFER_MINUTOS = 23  # quanto tempo de live fica guardado
CORTE_FORCADO_MINUTOS = 15  # se ficar esse tempo sem clipe, corta o melhor momento
MOTIVO_POR_TEMPO = "auto-por-tempo"  # vai no nome do clipe gerado pelo corte por tempo

# Qualidade da captura: "best", "1080p60", "720p60", "720p"...
QUALIDADE = "best"

# YouTube: True = usa yt-dlp | False = usa streamlink
USAR_YTDLP_NO_YOUTUBE = False

# ---------------------------------------------------------------------
#  DETECÇÃO (dispara quando score >= LIMIAR_SCORE)
#  Ex.: risada média sozinha (0.75 x 0.6 = 0.45) já dispara;
#       grito alto (+10 dB) com chat agitado também.
# ---------------------------------------------------------------------
LIMIAR_SCORE = 0.45
PESO_AUDIO = 0.6  # risada / grito / explosão (YAMNet)
PESO_VOLUME = 0.2  # volume acima da média do streamer
PESO_CHAT = 0.3  # pico de mensagens no chat

LIMIAR_MUSICA = 0.5  # se "Music" dominar o áudio, o evento é ignorado
DB_ACIMA_MEDIA_MIN = 5  # +5 dB acima da média começa a pontuar
DB_ACIMA_MEDIA_MAX = 10  # +10 dB = pontuação máxima de volume

PALAVRAS_CHAT = [
    "kkk",
    "kekw",
    "lul",
    "omegalul",
    "lmao",
    "rsrs",
    "hahaha",
    "mds",
    "caralho",
    "nossa",
    "pog",
    "omg",
    "😂",
    "🤣",
    "💀",
]

# ---------------------------------------------------------------------
#  CALIBRAÇÃO
#  A cada N segundos, loga o maior score do período (0 = desliga).
# ---------------------------------------------------------------------
INTERVALO_LOG_SCORE = 15

# ---------------------------------------------------------------------
#  LOG (autoclipper.log com rotação)
#  Ao chegar em LOG_MAX_MB, o arquivo vira .1, .2... e o mais antigo é apagado.
# ---------------------------------------------------------------------
LOG_MAX_MB = 5
LOG_BACKUPS = 3

# ---------------------------------------------------------------------
#  CONFIGURAÇÃO LOCAL
#  config_local.py (fora do Git) na raiz do projeto: os valores em
#  MAIÚSCULAS definidos lá substituem os daqui.
# ---------------------------------------------------------------------
ARQUIVO_CONFIG_LOCAL = PASTA_BASE / "config_local.py"


def _carregar_config_local(caminho: Path) -> None:
    if not caminho.is_file():
        return
    spec = importlib.util.spec_from_file_location("config_local", caminho)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    for nome, valor in vars(modulo).items():
        if nome.isupper():
            globals()[nome] = valor


_carregar_config_local(ARQUIVO_CONFIG_LOCAL)
