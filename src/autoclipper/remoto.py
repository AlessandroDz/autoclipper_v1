"""Acesso ao painel pelo celular, via Tailscale.

O painel continua escutando só em localhost. O `tailscale serve` repassa o
acesso para os aparelhos da sua rede Tailscale (sua conta), com o tráfego
criptografado pelo próprio Tailscale. Nada fica aberto na internet.
"""

import json
import logging
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger("main")

CAMINHOS_WINDOWS = [Path(r"C:\Program Files\Tailscale\tailscale.exe")]
_SEM_JANELA = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def caminho_tailscale() -> str | None:
    achado = shutil.which("tailscale")
    if achado:
        return achado
    for p in CAMINHOS_WINDOWS:
        if p.exists():
            return str(p)
    return None


def _rodar(args: list[str], timeout: float = 15) -> subprocess.CompletedProcess | None:
    exe = caminho_tailscale()
    if not exe:
        return None
    try:
        return subprocess.run(
            [exe, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=_SEM_JANELA,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        log.warning(f"Tailscale não respondeu: {e}")
        return None


def nome_na_rede(status_json: str) -> str | None:
    """Nome do PC na rede Tailscale, ex.: 'meupc.tail1234.ts.net'."""
    try:
        nome = json.loads(status_json)["Self"]["DNSName"]
    except (ValueError, KeyError, TypeError):
        return None
    return nome.rstrip(".") or None


def montar_endereco(nome: str, porta: int) -> str:
    return f"http://{nome}" if porta == 80 else f"http://{nome}:{porta}"


def endereco_remoto(porta_remota: int) -> str | None:
    r = _rodar(["status", "--json"])
    if not r or r.returncode != 0:
        return None
    nome = nome_na_rede(r.stdout)
    return montar_endereco(nome, porta_remota) if nome else None


def publicar_painel(porta_local: int, porta_remota: int) -> str | None:
    """Publica o painel na rede Tailscale. Retorna o endereço ou None se não deu."""
    if not caminho_tailscale():
        log.warning("Tailscale não encontrado: o painel fica só neste PC.")
        return None
    # fmt: off
    r = _rodar([
        "serve", "--bg", "--yes",
        f"--http={porta_remota}", f"http://localhost:{porta_local}",
    ])
    # fmt: on
    if not r or r.returncode != 0:
        erro = (r.stderr or r.stdout).strip() if r else "sem resposta"
        log.warning(f"Não consegui publicar o painel no Tailscale: {erro}")
        return None
    return endereco_remoto(porta_remota)
