import json
from pathlib import Path

import pytest

from autoclipper import config, lives
from autoclipper.gerenciador import Gerenciador

TWITCH = "https://www.twitch.tv/canal_a"
YOUTUBE = "https://www.youtube.com/watch?v=ABC123"


@pytest.fixture
def arquivo(tmp_path, monkeypatch):
    arq = tmp_path / "lives.json"
    monkeypatch.setattr(config, "ARQUIVO_LIVES", arq)
    monkeypatch.setattr(config, "PASTA_BUFFER", str(tmp_path / "buffer"))
    monkeypatch.setattr(config, "LINKS_DAS_LIVES", [TWITCH])
    return arq


def test_sem_lives_json_vale_o_config_local(arquivo):
    assert lives.carregar_links() == [TWITCH]


def test_lives_json_vale_no_lugar_do_config_local(arquivo):
    lives.salvar_links([YOUTUBE])
    assert lives.carregar_links() == [YOUTUBE]
    assert json.loads(arquivo.read_text(encoding="utf-8")) == {"links": [YOUTUBE]}


def test_lives_json_estragado_volta_para_o_config_local(arquivo):
    arquivo.write_text("{não é json", encoding="utf-8")
    assert lives.carregar_links() == [TWITCH]
    arquivo.write_text('{"links": "errado"}', encoding="utf-8")
    assert lives.carregar_links() == [TWITCH]


def test_adicionar_live_sem_reiniciar_e_salva(arquivo):
    g = Gerenciador()
    lista_antiga = g.monitores
    ok, msg = g.adicionar_live(YOUTUBE)

    assert ok and "ABC123" in msg
    assert [m.canal for m in g.monitores] == ["canal_a", "ABC123"]
    assert [m.canal for m in lista_antiga] == ["canal_a"]  # lista antiga intacta
    assert lives.carregar_links() == [TWITCH, YOUTUBE]


def test_adicionar_link_sem_https(arquivo):
    g = Gerenciador()
    ok, _ = g.adicionar_live("twitch.tv/canal_b")
    assert ok and g.monitores[-1].url == "https://twitch.tv/canal_b"


@pytest.mark.parametrize(
    "link", ["", "   ", "https://vimeo.com/x", "qualquer coisa", "https://www.twitch.tv/.."]
)
def test_adicionar_link_invalido_e_recusado(arquivo, link):
    g = Gerenciador()
    ok, _ = g.adicionar_live(link)
    assert not ok and len(g.monitores) == 1
    assert not arquivo.exists()  # nada foi salvo


def test_adicionar_live_repetida_e_recusada(arquivo):
    g = Gerenciador()
    ok, msg = g.adicionar_live("https://www.twitch.tv/CANAL_A/")  # mesmo canal
    assert not ok and "já está" in msg
    assert len(g.monitores) == 1


def test_remover_live_finaliza_e_salva(arquivo, monkeypatch):
    g = Gerenciador()
    g.adicionar_live(YOUTUBE)
    finalizados = []
    monkeypatch.setattr(g.monitor("canal_a"), "finalizar", lambda: finalizados.append(1))

    g.remover_live("canal_a")

    assert finalizados == [1]
    assert [m.canal for m in g.monitores] == ["ABC123"]
    assert lives.carregar_links() == [YOUTUBE]


def test_lista_explicita_nao_grava_arquivo(arquivo):
    g = Gerenciador(links=[TWITCH])
    g.adicionar_live(YOUTUBE)
    assert not arquivo.exists()


def test_lives_json_fica_fora_do_git():
    gitignore = Path(__file__).parents[1] / ".gitignore"
    linhas = gitignore.read_text(encoding="utf-8").splitlines()
    assert "lives.json" in linhas and "config_local.py" in linhas
