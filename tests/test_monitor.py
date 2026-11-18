import pytest

from autoclipper.monitor import identificar_live


@pytest.mark.parametrize(
    ("url", "esperado"),
    [
        ("https://www.twitch.tv/Canal_Teste", ("twitch", "canal_teste")),
        ("https://twitch.tv/canal/", ("twitch", "canal")),
        ("https://www.youtube.com/@MeuCanal/live", ("youtube", "MeuCanal")),
        ("https://www.youtube.com/live/AbC123xyz", ("youtube", "AbC123xyz")),
        ("https://www.youtube.com/watch?v=AbC123xyz", ("youtube", "AbC123xyz")),
        ("https://youtu.be/AbC123xyz", ("youtube", "AbC123xyz")),
        ("https://www.youtube.com/channel/UC_x-y", ("youtube", "UC_x-y")),
    ],
)
def test_identificar_live(url, esperado):
    assert identificar_live(url) == esperado


@pytest.mark.parametrize("url", ["https://kick.com/canal", "https://www.twitch.tv/", "nada"])
def test_identificar_live_link_invalido(url):
    with pytest.raises(ValueError):
        identificar_live(url)
