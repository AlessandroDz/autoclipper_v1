import json
import threading
import time

import pytest

from autoclipper.chat import LeitorChat, _textos_chat_youtube


def _linha_youtube(*runs):
    """Monta uma linha no formato do live_chat.json gerado pelo yt-dlp."""
    item = {"liveChatTextMessageRenderer": {"message": {"runs": list(runs)}}}
    return json.dumps(
        {"replayChatItemAction": {"actions": [{"addChatItemAction": {"item": item}}]}}
    )


def test_texto_simples():
    assert _textos_chat_youtube(_linha_youtube({"text": "kkkkk que isso"})) == ["kkkkk que isso"]


def test_emoji_unicode_e_emoji_personalizado():
    linha = _linha_youtube(
        {"text": "olha "},
        {"emoji": {"emojiId": "😂"}},
        {"emoji": {"emojiId": "UCabc/xyz", "shortcuts": [":pog:"]}},
    )
    assert _textos_chat_youtube(linha) == ["olha 😂:pog:"]


@pytest.mark.parametrize(
    "linha",
    [
        "isso não é json",
        json.dumps({"outroEvento": {}}),
        json.dumps({"replayChatItemAction": {"actions": [{"removeChatItemAction": {}}]}}),
    ],
)
def test_linhas_sem_mensagem_sao_ignoradas(linha):
    assert _textos_chat_youtube(linha) == []


# ---------------------------------------------------------------------
#  score do chat
# ---------------------------------------------------------------------
@pytest.fixture
def leitor():
    leitor = LeitorChat("twitch", "canal", "https://twitch.tv/canal", threading.Event())
    leitor.inicio = time.time() - 300  # finge 5 min de histórico
    return leitor


def _adicionar(leitor, quantidade, inicio_seg_atras, fim_seg_atras, palavra_chave=False):
    agora = time.time()
    passo = (inicio_seg_atras - fim_seg_atras) / quantidade
    for i in range(quantidade):
        leitor.msgs.append((agora - inicio_seg_atras + i * passo, palavra_chave))


def test_pouco_historico_da_zero(leitor):
    _adicionar(leitor, 10, 10, 0)
    assert leitor.score() == 0.0


def test_ritmo_normal_da_zero(leitor):
    _adicionar(leitor, 60, 300, 0)  # ritmo constante de 1 msg a cada 5 s
    assert leitor.score() == 0.0


def test_pico_de_mensagens_da_score_maximo(leitor):
    _adicionar(leitor, 30, 300, 10)  # ritmo base baixo
    _adicionar(leitor, 20, 10, 0)  # explosão nos últimos 10 s
    assert leitor.score() == pytest.approx(1.0)


def test_palavras_chave_somam_bonus():
    def cenario(palavra_chave):
        leitor = LeitorChat("twitch", "canal", "https://twitch.tv/canal", threading.Event())
        leitor.inicio = time.time() - 300
        _adicionar(leitor, 60, 300, 10)
        _adicionar(leitor, 5, 10, 0, palavra_chave=palavra_chave)  # leve aumento no ritmo
        return leitor.score()

    sem_kw, com_kw = cenario(False), cenario(True)
    assert 0 < sem_kw < 0.7
    assert com_kw == pytest.approx(sem_kw + 0.3)


def test_registrar_detecta_palavra_chave(leitor):
    leitor._registrar("KKKKKK mds")
    leitor._registrar("boa noite")
    assert [kw for _, kw in leitor.msgs] == [True, False]
