from pathlib import Path

from autoclipper import config


def test_config_versionado_nao_tem_dados_pessoais():
    # o config.py vai para o GitHub: links ficam vazios e pastas são relativas ao projeto
    fonte = Path(config.__file__).read_text(encoding="utf-8")
    assert "LINKS_DAS_LIVES: list[str] = []" in fonte
    assert "C:\\Users" not in fonte
    assert "Meu Drive\\videos" not in fonte


def test_config_local_substitui_so_maiusculas(tmp_path, monkeypatch):
    arquivo = tmp_path / "config_local.py"
    arquivo.write_text(
        'LINKS_DAS_LIVES = ["https://www.twitch.tv/teste"]\n'
        "LIMIAR_SCORE = 0.42\n"
        "variavel_minuscula = 123\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "LINKS_DAS_LIVES", [])
    monkeypatch.setattr(config, "LIMIAR_SCORE", 0.55)

    config._carregar_config_local(arquivo)

    assert config.LINKS_DAS_LIVES == ["https://www.twitch.tv/teste"]
    assert config.LIMIAR_SCORE == 0.42
    assert not hasattr(config, "variavel_minuscula")


def test_config_local_inexistente_nao_quebra(tmp_path):
    config._carregar_config_local(tmp_path / "nao_existe.py")
