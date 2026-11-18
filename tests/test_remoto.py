import json
import subprocess

from autoclipper import remoto


def test_nome_na_rede_tira_o_ponto_final():
    status = json.dumps({"Self": {"DNSName": "meupc.tail1234.ts.net."}})
    assert remoto.nome_na_rede(status) == "meupc.tail1234.ts.net"


def test_nome_na_rede_com_resposta_estranha():
    assert remoto.nome_na_rede("não é json") is None
    assert remoto.nome_na_rede(json.dumps({"Self": {}})) is None
    assert remoto.nome_na_rede(json.dumps({"Self": {"DNSName": ""}})) is None


def test_montar_endereco():
    assert remoto.montar_endereco("pc.ts.net", 80) == "http://pc.ts.net"
    assert remoto.montar_endereco("pc.ts.net", 8080) == "http://pc.ts.net:8080"


def test_sem_tailscale_o_painel_continua_local(monkeypatch):
    monkeypatch.setattr(remoto, "caminho_tailscale", lambda: None)
    assert remoto.publicar_painel(8501, 80) is None
    assert remoto.endereco_remoto(80) is None


def test_publicar_painel_chama_serve_so_na_rede_tailscale(monkeypatch):
    chamadas = []

    def rodar_falso(args, timeout=15):
        chamadas.append(args)
        saida = json.dumps({"Self": {"DNSName": "pc.tail1.ts.net."}})
        return subprocess.CompletedProcess(args, 0, stdout=saida, stderr="")

    monkeypatch.setattr(remoto, "caminho_tailscale", lambda: "tailscale")
    monkeypatch.setattr(remoto, "_rodar", rodar_falso)

    assert remoto.publicar_painel(8501, 80) == "http://pc.tail1.ts.net"
    serve = chamadas[0]
    assert serve[0] == "serve" and "--http=80" in serve
    assert "http://localhost:8501" in serve
    assert not any("funnel" in a for a in serve)  # nunca abre para a internet


def test_falha_no_serve_nao_derruba(monkeypatch):
    monkeypatch.setattr(remoto, "caminho_tailscale", lambda: "tailscale")
    monkeypatch.setattr(
        remoto,
        "_rodar",
        lambda args, timeout=15: subprocess.CompletedProcess(args, 1, stdout="", stderr="erro"),
    )
    assert remoto.publicar_painel(8501, 80) is None
