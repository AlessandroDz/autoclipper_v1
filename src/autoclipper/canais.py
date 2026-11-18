"""Ajustes por canal (layout do vertical e posição da câmera), salvos em canais.json.

Formato do arquivo:
    {"skipnho": {"layout": "A", "camera": [x, y, largura, altura]}}
A câmera é guardada em frações do quadro (0 a 1), então vale para qualquer resolução.
"""

import json
import threading
from pathlib import Path

from . import config

LAYOUTS = ("A", "C")
_lock = threading.Lock()


def _arquivo() -> Path:
    return Path(config.ARQUIVO_CANAIS)


def carregar() -> dict:
    try:
        return json.loads(_arquivo().read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def obter(canal: str) -> dict:
    """Ajustes do canal com os valores padrão preenchidos."""
    dados = carregar().get(canal, {})
    layout = dados.get("layout", config.LAYOUT_PADRAO)
    camera = dados.get("camera")
    return {
        "layout": layout if layout in LAYOUTS else config.LAYOUT_PADRAO,
        "camera": camera if camera_valida(camera) else None,
    }


def layout_efetivo(canal: str) -> str:
    """O layout que será usado de fato: "A" sem câmera marcada cai para "C"."""
    ajustes = obter(canal)
    if ajustes["layout"] == "A" and ajustes["camera"]:
        return "A"
    return "C"


def definir(canal: str, **campos) -> None:
    with _lock:
        dados = carregar()
        dados.setdefault(canal, {}).update(campos)
        arq = _arquivo()
        temp = arq.with_suffix(".tmp")
        temp.write_text(json.dumps(dados, indent=2, ensure_ascii=False), encoding="utf-8")
        temp.replace(arq)  # troca atômica: nunca deixa o arquivo pela metade


def camera_valida(camera) -> bool:
    if not isinstance(camera, (list, tuple)) or len(camera) != 4:
        return False
    try:
        x, y, w, h = (float(v) for v in camera)
    except (TypeError, ValueError):
        return False
    return (
        0 <= x < 1
        and 0 <= y < 1
        and 0 < w <= 1
        and 0 < h <= 1
        and x + w <= 1.001
        and (y + h <= 1.001)
    )
