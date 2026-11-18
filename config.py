# =====================================================================
#                    CONFIGURAÇÃO DO AUTO-CLIPPER (v1)
# =====================================================================
from pathlib import Path

# ---------------------------------------------------------------------
#  >>> LINKS DAS LIVES <<<   (Twitch ou YouTube, um por linha)
# ---------------------------------------------------------------------
LINKS_DAS_LIVES = [
    "https://www.twitch.tv/CANAL",
    "https://www.youtube.com/live/ID_DO_VIDEO",
]

# ---------------------------------------------------------------------
#  PASTAS
# ---------------------------------------------------------------------
# Onde os clipes finais são salvos (padrão: pasta "videos" dentro do projeto).
# Para acessar pelo celular, aponte para o Google Drive para desktop,
# ex.: r"G:\Meu Drive\Clipes"
PASTA_CLIPES = str(Path(__file__).parent / "videos")

# Buffer temporário (pedaços de 10s das lives). NÃO coloque dentro do Drive.
PASTA_BUFFER = str(Path(__file__).parent / "buffer")

# ---------------------------------------------------------------------
#  CLIPE
# ---------------------------------------------------------------------
SEGUNDOS_ANTES = 60  # 1 min antes da flag
SEGUNDOS_DEPOIS = 120  # 2 min depois da flag
DURACAO_SEGMENTO = 10  # tamanho de cada pedaço do buffer (s)
BUFFER_MINUTOS = 23  # quanto tempo de live fica guardado
CORTE_FORCADO_MINUTOS = 20  # se ficar esse tempo sem clipe, corta o melhor momento

# Qualidade da captura: "best", "1080p60", "720p60", "720p"...
QUALIDADE = "best"

# YouTube: True = usa yt-dlp | False = usa streamlink
USAR_YTDLP_NO_YOUTUBE = False

# ---------------------------------------------------------------------
#  DETECÇÃO (dispara quando score >= LIMIAR_SCORE)
#  Ex.: risada forte sozinha (0.95 x 0.6 = 0.57) já dispara;
#       volume + chat sem risada/grito/explosão (0.5) não dispara.
# ---------------------------------------------------------------------
LIMIAR_SCORE = 0.55
PESO_AUDIO = 0.6  # risada / grito / explosão (YAMNet)
PESO_VOLUME = 0.2  # volume acima da média do streamer
PESO_CHAT = 0.3  # pico de mensagens no chat

LIMIAR_MUSICA = 0.5  # se "Music" dominar o áudio, o evento é ignorado
DB_ACIMA_MEDIA_MIN = 6  # +6 dB acima da média começa a pontuar
DB_ACIMA_MEDIA_MAX = 12  # +12 dB = pontuação máxima de volume

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
#  Crie um config_local.py (fica fora do Git) com seus links e pastas;
#  qualquer valor definido lá substitui o daqui.
# ---------------------------------------------------------------------
try:
    from config_local import *  # noqa: F401,F403
except ImportError:
    pass
