"""Abre o painel no navegador.  Rode da raiz do projeto com:  python -m autoclipper.painel

Por enquanto o painel só aceita conexões do próprio PC (localhost).
"""

import sys
import threading
import time
import webbrowser
from pathlib import Path

PORTA = 8501
ENDERECO = f"http://localhost:{PORTA}"


def main():
    from streamlit.web import cli as stcli

    app = Path(__file__).with_name("painel_app.py")
    # abre o navegador quando o servidor já estiver de pé
    threading.Thread(target=lambda: (time.sleep(4), webbrowser.open(ENDERECO)), daemon=True).start()
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
