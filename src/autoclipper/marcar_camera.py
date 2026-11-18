"""Marca a posição da câmera do streamer (uma vez por canal).

Pega um quadro da live, abre uma janela e você arrasta um retângulo em cima da
câmera. ENTER confirma, ESC cancela. A posição é salva em canais.json e o canal
passa a usar o layout A.

Uso (o painel chama isto pelo botão "Marcar câmera"):
    python -m autoclipper.marcar_camera <canal> <link da live>
"""

import subprocess
import sys
import tempfile
import time
from pathlib import Path

from . import canais, config
from .monitor import FORMATO_SEG
from .sistema import garantir_ffmpeg

TITULO = "Marque a camera do streamer: arraste e aperte ENTER (ESC cancela)"


def quadro_do_buffer(canal: str, destino: Path) -> bool:
    """Usa o penúltimo pedaço do buffer (o último pode estar sendo gravado)."""
    pasta = Path(config.PASTA_BUFFER) / canal
    segs = []
    for arq in pasta.glob("seg_*.ts"):
        try:
            segs.append((time.mktime(time.strptime(arq.stem, FORMATO_SEG)), arq))
        except ValueError:
            pass
    segs.sort()
    if len(segs) < 2:
        return False
    # fmt: off
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(segs[-2][1]),
           "-frames:v", "1", str(destino)]
    # fmt: on
    return subprocess.run(cmd, capture_output=True).returncode == 0 and destino.exists()


def quadro_da_live(url: str, destino: Path) -> bool:
    """Conecta na live só para pegar um quadro (quando ela não está sendo monitorada)."""
    # fmt: off
    p1 = subprocess.Popen([sys.executable, "-m", "streamlink", "--stdout", "--loglevel", "error",
                           url, config.QUALIDADE], stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL)
    p2 = subprocess.Popen(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
                           "-frames:v", "1", str(destino)], stdin=p1.stdout,
                          stderr=subprocess.DEVNULL)
    # fmt: on
    p1.stdout.close()
    try:
        p2.wait(timeout=60)
    except subprocess.TimeoutExpired:
        p2.kill()
    finally:
        p1.kill()
    return destino.exists() and destino.stat().st_size > 0


def selecionar(imagem_path: Path):
    """Abre a janela de seleção e devolve (x, y, w, h) em frações, ou None."""
    import cv2

    img = cv2.imread(str(imagem_path))
    if img is None:
        return None
    altura, largura = img.shape[:2]
    escala = min(1280 / largura, 720 / altura, 1.0)  # cabe na tela
    tela = cv2.resize(img, (int(largura * escala), int(altura * escala)))

    x, y, w, h = cv2.selectROI(TITULO, tela, showCrosshair=False, fromCenter=False)
    cv2.destroyAllWindows()
    if w < 5 or h < 5:
        return None
    th, tw = tela.shape[:2]
    return [round(x / tw, 5), round(y / th, 5), round(w / tw, 5), round(h / th, 5)]


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if len(argv) < 2:
        print("Uso: python -m autoclipper.marcar_camera <canal> <link da live>")
        return 2
    canal, url = argv[0], argv[1]
    if not garantir_ffmpeg():
        print("ffmpeg não encontrado.")
        return 1

    with tempfile.TemporaryDirectory() as tmp:
        quadro = Path(tmp) / "quadro.png"
        print(f"Pegando um quadro de {canal}...")
        if not (quadro_do_buffer(canal, quadro) or quadro_da_live(url, quadro)):
            print("Não consegui pegar um quadro: a live está offline?")
            return 1
        camera = selecionar(quadro)

    if camera is None:
        print("Cancelado: nada foi alterado.")
        return 0
    canais.definir(canal, camera=camera, layout="A")
    print(f"Câmera de {canal} salva: {camera}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
