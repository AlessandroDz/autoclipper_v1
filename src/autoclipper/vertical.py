"""Formato vertical 9:16 e fila de processamento dos clipes.

Cada clipe chega aqui como um arquivo 16:9 temporário (cortado sem recodificar).
A fila processa um por vez:
  1. gera o vertical 1080x1920 (layout A ou C) recodificando com ffmpeg;
  2. move o vertical para PASTA_VERTICAL\\<canal>\\ e o original para PASTA_ORIGINAIS\\<canal>\\.
Os arquivos são gerados fora do Drive e só movidos prontos (o Drive nunca
sincroniza arquivo pela metade).
"""

import logging
import queue
import shutil
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path

from . import canais, config

log = logging.getLogger("vertical")


# =====================================================================
#  FILTROS DO FFMPEG
# =====================================================================
def _par(n: float) -> int:
    """Arredonda para número par (exigência do H.264 com yuv420p)."""
    return int(round(n / 2)) * 2


def medidas_layout_a():
    """(altura da faixa, altura da gameplay, altura da câmera) no layout A."""
    altura = config.VERTICAL_ALTURA
    faixa = _par(config.FAIXA_TOPO_PX)
    cam = _par(altura * config.CAMERA_PCT)
    return faixa, altura - faixa - cam, cam


def filtro_layout_a(camera) -> str:
    """Faixa vazia no topo + gameplay (centro da live) + câmera do streamer embaixo."""
    largura, fps = config.VERTICAL_LARGURA, config.VERTICAL_FPS
    faixa, gh, ch = medidas_layout_a()
    cx, cy, cw, cam_h = (float(v) for v in camera)
    return (
        "[0:v]split=2[g][c];"
        # gameplay: recorta o centro na proporção da área e ajusta ao tamanho
        f"[g]crop=w='min(iw,ih*{largura}/{gh})':h='min(ih,iw*{gh}/{largura})',"
        f"scale={largura}:{gh},setsar=1[gp];"
        # câmera: recorta o retângulo marcado, preenche a área e corta o excesso
        f"[c]crop=w=iw*{cw:.5f}:h=ih*{cam_h:.5f}:x=iw*{cx:.5f}:y=ih*{cy:.5f},"
        f"scale={largura}:{ch}:force_original_aspect_ratio=increase,"
        f"crop={largura}:{ch},setsar=1[cam];"
        f"[gp][cam]vstack=inputs=2,pad={largura}:{config.VERTICAL_ALTURA}:0:{faixa}:black,"
        f"fps={fps},format=yuv420p[v]"
    )


def filtro_layout_c() -> str:
    """Vídeo inteiro no centro, com o próprio vídeo desfocado preenchendo o fundo."""
    largura, altura, fps = config.VERTICAL_LARGURA, config.VERTICAL_ALTURA, config.VERTICAL_FPS
    pl, pa = largura // 4, altura // 4  # desfoca em tamanho reduzido: bem mais leve
    return (
        "[0:v]split=2[a][b];"
        f"[a]scale={pl}:{pa}:force_original_aspect_ratio=increase,crop={pl}:{pa},"
        f"boxblur=12:2,scale={largura}:{altura},setsar=1[fundo];"
        f"[b]scale={largura}:-2,setsar=1[frente];"
        f"[fundo][frente]overlay=(W-w)/2:(H-h)/2,fps={fps},format=yuv420p[v]"
    )


def filtro(layout: str, camera=None) -> str:
    if layout == "A" and canais.camera_valida(camera):
        return filtro_layout_a(camera)
    return filtro_layout_c()


# =====================================================================
#  CODIFICADOR (placa AMD via AMF ou processador)
# =====================================================================
_amf_disponivel = None


def amf_disponivel() -> bool:
    """Testa uma única vez se o ffmpeg consegue codificar com a placa AMD."""
    global _amf_disponivel
    if _amf_disponivel is None:
        # fmt: off
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
               "-i", "testsrc2=s=256x256:r=30", "-t", "0.5", "-c:v", "h264_amf",
               "-f", "null", "-"]
        # fmt: on
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=30)
            _amf_disponivel = r.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            _amf_disponivel = False
        log.info(f"Codificador: {'placa AMD (AMF)' if _amf_disponivel else 'processador'}")
    return _amf_disponivel


def argumentos_codificador(tipo: str) -> list[str]:
    taxa = config.VERTICAL_BITRATE
    # fmt: off
    if tipo == "amf":
        return ["-c:v", "h264_amf", "-quality", "balanced", "-rc", "vbr_peak",
                "-b:v", taxa, "-maxrate", "12M"]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
            "-maxrate", "12M", "-bufsize", "24M"]
    # fmt: on


def ordem_codificadores() -> list[str]:
    escolha = config.CODIFICADOR
    if escolha == "cpu":
        return ["cpu"]
    if escolha == "amf":
        return ["amf", "cpu"]
    return ["amf", "cpu"] if amf_disponivel() else ["cpu"]


def comando_vertical(entrada: Path, saida: Path, layout: str, camera, codificador: str):
    # fmt: off
    return [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(entrada),
        "-filter_complex", filtro(layout, camera),
        "-map", "[v]", "-map", "0:a:0?",
        *argumentos_codificador(codificador),
        "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
        "-movflags", "+faststart", str(saida),
    ]
    # fmt: on


def gerar_vertical(entrada: Path, saida: Path, layout: str, camera) -> bool:
    """Gera o vertical; se a placa falhar, tenta de novo no processador."""
    for cod in ordem_codificadores():
        r = subprocess.run(
            comando_vertical(entrada, saida, layout, camera, cod), capture_output=True, text=True
        )
        if r.returncode == 0 and saida.exists() and saida.stat().st_size > 0:
            return True
        log.warning(f"Falha ao gerar vertical ({cod}): {r.stderr.strip()[-300:]}")
        saida.unlink(missing_ok=True)
    return False


# =====================================================================
#  FILA (um clipe por vez, para não atrapalhar a captura das lives)
# =====================================================================
@dataclass
class Trabalho:
    canal: str
    nome: str  # nome final do arquivo, igual no vertical e no original
    original_temp: Path
    ao_terminar: object = field(default=None, repr=False)  # callback(trabalho, ok)


class FilaVertical:
    def __init__(self):
        self.fila: queue.Queue[Trabalho] = queue.Queue()
        self.atual: Trabalho | None = None
        threading.Thread(target=self._loop, daemon=True, name="fila-vertical").start()

    def adicionar(self, trabalho: Trabalho) -> None:
        self.fila.put(trabalho)

    def tamanho(self) -> int:
        return self.fila.qsize() + (1 if self.atual else 0)

    def _loop(self):
        while True:
            trabalho = self.fila.get()
            self.atual = trabalho
            ok = False
            try:
                ok = self._processar(trabalho)
            except Exception as e:  # um clipe com problema nunca pode parar a fila
                log.error(f"[{trabalho.canal}] Erro ao processar {trabalho.nome}: {e}")
            finally:
                self.atual = None
                if trabalho.ao_terminar:
                    trabalho.ao_terminar(trabalho, ok)

    def _processar(self, t: Trabalho) -> bool:
        clog = logging.getLogger(t.canal)
        destino_vert = Path(config.PASTA_VERTICAL) / t.canal / t.nome
        destino_orig = Path(config.PASTA_ORIGINAIS) / t.canal / t.nome
        destino_vert.parent.mkdir(parents=True, exist_ok=True)

        ajustes = canais.obter(t.canal)
        layout = canais.layout_efetivo(t.canal)
        temp_vert = t.original_temp.with_name(f"vert_{t.nome}")
        ok = gerar_vertical(t.original_temp, temp_vert, layout, ajustes["camera"])
        if ok:
            shutil.move(str(temp_vert), str(destino_vert))
            clog.info(f"CLIPE SALVO (layout {layout}): {destino_vert}")
        else:
            clog.error(f"Vertical não gerado para {t.nome} (o original foi salvo no lugar).")

        # o original só é guardado se configurado - ou se o vertical falhou
        if config.SALVAR_ORIGINAIS or not ok:
            destino_orig.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(t.original_temp), str(destino_orig))
            clog.info(f"ORIGINAL SALVO: {destino_orig}")
        else:
            t.original_temp.unlink(missing_ok=True)
        return ok
