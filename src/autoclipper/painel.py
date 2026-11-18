"""Abre o painel no navegador.  Rode da raiz do projeto com:  python -m autoclipper.painel

Se o painel já estiver aberto, só abre a página no navegador (não abre uma
segunda cópia). Por enquanto o painel só aceita conexões do próprio PC (localhost).
"""

import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

PORTA = 8501
ENDERECO = f"http://localhost:{PORTA}"


def painel_no_ar(timeout: float = 2.0) -> bool:
    """True se já existe um painel respondendo nesta porta."""
    try:
        with urllib.request.urlopen(f"{ENDERECO}/_stcore/health", timeout=timeout) as r:
            return r.status == 200
    except OSError:
        return False


def abrir_navegador_quando_pronto(limite_s: float = 90) -> None:
    """Espera o servidor responder e só então abre a página."""
    inicio = time.time()
    while time.time() - inicio < limite_s:
        if painel_no_ar(timeout=1):
            webbrowser.open(ENDERECO)
            return
        time.sleep(0.5)
    print(f"O painel demorou para subir. Abra manualmente: {ENDERECO}")


def main():
    if painel_no_ar():
        print(f"O painel já está aberto: abrindo {ENDERECO} no navegador.")
        webbrowser.open(ENDERECO)
        return

    from streamlit.web import cli as stcli

    app = Path(__file__).with_name("painel_app.py")
    threading.Thread(target=abrir_navegador_quando_pronto, daemon=True).start()
    print(f"Painel em {ENDERECO}  (feche esta janela para desligar o Auto-Clipper)")
    # fmt: off
    sys.argv = [
        "streamlit", "run", str(app),
        "--server.address", "localhost", "--server.port", str(PORTA),
        "--server.headless", "true", "--server.runOnSave", "false",
        "--browser.gatherUsageStats", "false",
        "--client.toolbarMode", "minimal",  # esconde o botão "Deploy" do Streamlit
    ]
    # fmt: on
    sys.exit(stcli.main())


if __name__ == "__main__":
    main()
