import os
import time

import pytest

from autoclipper import config
from autoclipper.gerenciador import Gerenciador, ler_nome_clipe
from autoclipper.monitor import PARADA, MonitorLive, nome_do_clipe


@pytest.fixture
def pastas(tmp_path, monkeypatch):
    vert, orig = tmp_path / "vertical", tmp_path / "originais"
    monkeypatch.setattr(config, "PASTA_VERTICAL", str(vert))
    monkeypatch.setattr(config, "PASTA_ORIGINAIS", str(orig))
    monkeypatch.setattr(config, "PASTA_BUFFER", str(tmp_path / "buffer"))
    return vert, orig


def _criar(pasta, canal, nome, idade_dias=0):
    arq = pasta / canal / nome
    arq.parent.mkdir(parents=True, exist_ok=True)
    arq.write_bytes(b"x")
    t = time.time() - idade_dias * 86400
    os.utime(arq, (t, t))
    return arq


# ---------------------------------------------------------------------
#  nomes dos clipes
# ---------------------------------------------------------------------
def test_nome_do_clipe_por_tempo_fica_identificado():
    t = time.mktime((2026, 11, 18, 21, 40, 12, 0, 0, -1))
    nome = nome_do_clipe("burn", t, config.MOTIVO_POR_TEMPO)
    assert nome == "burn_2026-11-18_21-40-12_auto-por-tempo.mp4"


@pytest.mark.parametrize(
    ("nome", "esperado"),
    [
        ("burn_2026-11-18_21-40-12_risada.mp4", ("burn", "2026-11-18 21:40:12", "risada")),
        (
            "meu_canal_2026-11-18_01-02-03_manual.mp4",
            ("meu_canal", "2026-11-18 01:02:03", "manual"),
        ),
        (
            "x_2026-11-18_01-02-03_auto-por-tempo.mp4",
            ("x", "2026-11-18 01:02:03", "auto-por-tempo"),
        ),
        ("qualquer_coisa.mp4", None),
    ],
)
def test_ler_nome_clipe(nome, esperado):
    assert ler_nome_clipe(nome) == esperado


# ---------------------------------------------------------------------
#  lista e limpeza de clipes
# ---------------------------------------------------------------------
def test_listar_clipes_mais_recentes_primeiro(pastas):
    vert, _ = pastas
    _criar(vert, "burn", "burn_2026-11-10_10-00-00_risada.mp4", idade_dias=8)
    _criar(vert, "rodil", "rodil_2026-11-18_10-00-00_manual.mp4", idade_dias=0)
    _criar(vert, "rodil", "lixo.mp4")  # nome fora do padrão é ignorado

    clipes = Gerenciador(links=[]).listar_clipes()
    assert [c.canal for c in clipes] == ["rodil", "burn"]
    assert clipes[0].motivo == "manual"


def test_apagar_clipes_antigos_vertical_e_original(pastas):
    vert, orig = pastas
    velho = "burn_2026-11-01_10-00-00_risada.mp4"
    novo = "burn_2026-11-18_10-00-00_grito.mp4"
    for pasta in (vert, orig):
        _criar(pasta, "burn", velho, idade_dias=10)
        _criar(pasta, "burn", novo, idade_dias=1)

    g = Gerenciador(links=[])
    assert len(g.clipes_antigos(7)) == 2  # vertical + original do clipe velho
    assert g.apagar_clipes_antigos(7) == 2
    assert not (vert / "burn" / velho).exists() and not (orig / "burn" / velho).exists()
    assert (vert / "burn" / novo).exists() and (orig / "burn" / novo).exists()


# ---------------------------------------------------------------------
#  monitor
# ---------------------------------------------------------------------
def test_link_invalido_nao_derruba_o_gerenciador(pastas):
    g = Gerenciador(links=["https://www.twitch.tv/burn", "https://kick.com/x", " "])
    assert [m.canal for m in g.monitores] == ["burn"]
    assert g.status()[0]["estado"] == PARADA


def test_clipar_com_live_parada_e_recusado(pastas):
    m = MonitorLive("https://www.twitch.tv/burn", fila=None)
    ok, motivo = m.clipar_agora()
    assert not ok and "ao vivo" in motivo


def test_segmentos_de_antes_da_pausa_nao_entram_no_clipe(pastas, tmp_path):
    m = MonitorLive("https://www.twitch.tv/burn", fila=None)
    base = 1_000_000.0
    segs = [(base + i * 10, tmp_path / f"s{i}.ts") for i in range(10)]  # 0..90 s
    retomada = base + 50  # pausou e voltou: sessão nova começa em 50 s

    escolhidos = m.selecionar_segmentos(segs, base, base + 100, retomada)
    assert [s for s, _ in escolhidos] == [base + 50, base + 60, base + 70, base + 80, base + 90]


def test_finalizar_corta_na_hora_os_clipes_pendentes(pastas, monkeypatch):
    """Um clipe esperando os 2 min não pode ser perdido ao finalizar a live."""
    m = MonitorLive("https://www.twitch.tv/burn", fila=None)
    cortes = []

    def cortar_falso(t, motivo, score, inicio_sessao, cortar_agora):
        acordou = cortar_agora.wait(timeout=60)  # o real esperaria os 2 min
        cortes.append((motivo, acordou))
        return True

    monkeypatch.setattr(m, "_cortar_original", cortar_falso)
    m.estado = "ao_vivo"
    m._disparar(time.time(), "risada", 0.6)

    inicio = time.time()
    m.finalizar()
    assert time.time() - inicio < 5  # não esperou os 2 min
    assert cortes == [("risada", True)]
    assert m.estado == PARADA


def test_segmentos_cobrem_o_intervalo(pastas, tmp_path):
    m = MonitorLive("https://www.twitch.tv/burn", fila=None)
    segs = [(float(i * 10), tmp_path / f"s{i}.ts") for i in range(10)]
    escolhidos = m.selecionar_segmentos(segs, 25, 45, inicio_sessao=0)
    assert [s for s, _ in escolhidos] == [20.0, 30.0, 40.0]


# ---------------------------------------------------------------------
#  encerrar tudo
# ---------------------------------------------------------------------
def test_encerrar_tudo_confere_que_nada_ficou_aberto(pastas, monkeypatch):
    from autoclipper import sistema

    respostas = iter([[111], []])  # um programa ainda fechando, depois nenhum
    monkeypatch.setattr(sistema, "processos_filhos", lambda: next(respostas, []))
    forcados = []
    monkeypatch.setattr(sistema, "forcar_encerramento", forcados.extend)

    mensagens = []
    resumo = Gerenciador(links=[]).encerrar_tudo(progresso=mensagens.append)
    assert resumo == {"fila_restante": 0, "processos_abertos": 0, "forcados": 0}
    assert forcados == [] and mensagens


def test_encerrar_tudo_forca_o_que_nao_fechou(pastas, monkeypatch):
    from autoclipper import sistema

    estado = {"vivos": [222, 333]}
    monkeypatch.setattr(sistema, "processos_filhos", lambda: list(estado["vivos"]))

    def forcar(pids):
        estado["vivos"] = []

    monkeypatch.setattr(sistema, "forcar_encerramento", forcar)
    resumo = Gerenciador(links=[]).encerrar_tudo(espera_processos_s=0.1)
    assert resumo["forcados"] == 2 and resumo["processos_abertos"] == 0


def test_encerrar_tudo_sem_job_nao_quebra(pastas, monkeypatch):
    from autoclipper import sistema

    monkeypatch.setattr(sistema, "processos_filhos", lambda: None)
    resumo = Gerenciador(links=[]).encerrar_tudo()
    assert resumo["processos_abertos"] is None
