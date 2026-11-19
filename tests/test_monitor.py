import pytest

from autoclipper import config
from autoclipper.chat import LeitorChat
from autoclipper.monitor import MonitorLive, identificar_live


@pytest.mark.parametrize(
    ("url", "esperado"),
    [
        ("https://www.twitch.tv/Canal_Teste", ("twitch", "canal_teste")),
        ("https://twitch.tv/canal/", ("twitch", "canal")),
        ("https://m.twitch.tv/canal", ("twitch", "canal")),
        ("https://www.youtube.com/@MeuCanal/live", ("youtube", "MeuCanal")),
        ("https://www.youtube.com/live/AbC123xyz", ("youtube", "AbC123xyz")),
        ("https://www.youtube.com/watch?v=AbC123xyz", ("youtube", "AbC123xyz")),
        ("https://youtu.be/AbC123xyz", ("youtube", "AbC123xyz")),
        ("https://www.youtube.com/channel/UC_x-y", ("youtube", "UC_x-y")),
        ("https://kick.com/DavyJones", ("kick", "davyjones")),
        ("https://www.kick.com/canal-com_hifen/", ("kick", "canal-com_hifen")),
        ("https://kick.com/canal?clip=abc", ("kick", "canal")),
    ],
)
def test_identificar_live(url, esperado):
    assert identificar_live(url) == esperado


@pytest.mark.parametrize(
    "url",
    [
        "https://www.twitch.tv/",
        "nada",
        "https://vimeo.com/canal",
        "https://kick.com/",
        "https://kick.com/video/abc",
        "https://kick.com/categories/games",
    ],
)
def test_identificar_live_link_invalido(url):
    with pytest.raises(ValueError):
        identificar_live(url)


@pytest.mark.parametrize(
    "url",
    [
        # nomes que levariam a pasta do buffer para fora dela (e seriam apagados)
        "https://www.twitch.tv/..",
        "https://www.twitch.tv/.",
        r"https://www.twitch.tv/..\..",
        "https://www.twitch.tv/C:",
        "https://kick.com/..",
        r"https://kick.com/..\..",
        # site parecido não conta como o site de verdade
        "https://twitch.tv.site-qualquer.com/canal",
        "https://eviltwitch.tv/canal",
        "https://kick.com.site-qualquer.com/canal",
        "https://youtube.com.site-qualquer.com/watch?v=abc",
    ],
)
def test_link_perigoso_ou_falso_e_recusado(url):
    with pytest.raises(ValueError):
        identificar_live(url)


def test_youtube_com_pontos_nao_sai_da_pasta():
    _, canal = identificar_live("https://www.youtube.com/watch?v=..")
    assert canal == "__"


def test_pasta_do_buffer_sempre_dentro_do_buffer(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PASTA_BUFFER", str(tmp_path / "buffer"))
    raiz = (tmp_path / "buffer").resolve()
    for url in ["https://www.twitch.tv/canal", "https://kick.com/canal-x", "https://youtu.be/a.b"]:
        pasta = MonitorLive(url, fila=None).pasta_buffer.resolve()
        assert pasta.parent == raiz


def test_link_de_clipe_do_kick_vira_link_da_live():
    m = MonitorLive("https://kick.com/DavyJones?clip=abc123", fila=None)
    assert m.url == "https://kick.com/davyjones"


def test_kick_monitora_sem_chat(monkeypatch):
    import threading

    iniciadas = []
    monkeypatch.setattr(threading.Thread, "start", lambda self: iniciadas.append(self))
    leitor = LeitorChat("kick", "canal", "https://kick.com/canal", threading.Event())
    leitor.iniciar()
    assert iniciadas == []  # não tenta conectar em nada
    assert leitor.score() == 0.0
