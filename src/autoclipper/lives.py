"""Lista de lives monitoradas, editável pelo painel, salva em lives.json.

Enquanto o lives.json não existe, vale o LINKS_DAS_LIVES do config_local.py.
Depois que a lista é alterada pelo painel, o lives.json passa a valer.

Formato do arquivo:
    {"links": ["https://www.twitch.tv/CANAL", "https://www.youtube.com/watch?v=ID"]}
"""

import json
import threading
from pathlib import Path

from . import config

_lock = threading.Lock()


def _arquivo() -> Path:
    return Path(config.ARQUIVO_LIVES)


def carregar_links() -> list[str]:
    try:
        dados = json.loads(_arquivo().read_text(encoding="utf-8"))
        links = dados["links"]
        if isinstance(links, list) and all(isinstance(u, str) for u in links):
            return links
    except (FileNotFoundError, ValueError, KeyError, TypeError):
        pass
    return list(config.LINKS_DAS_LIVES)


def salvar_links(links: list[str]) -> None:
    with _lock:
        arq = _arquivo()
        temp = arq.with_suffix(".tmp")
        temp.write_text(
            json.dumps({"links": list(links)}, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        temp.replace(arq)  # troca atômica: nunca deixa o arquivo pela metade
