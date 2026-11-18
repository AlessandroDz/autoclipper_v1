import pytest

from autoclipper import canais, config, vertical


@pytest.fixture
def arquivo_canais(tmp_path, monkeypatch):
    arq = tmp_path / "canais.json"
    monkeypatch.setattr(config, "ARQUIVO_CANAIS", arq)
    return arq


# ---------------------------------------------------------------------
#  medidas e filtros
# ---------------------------------------------------------------------
def test_layout_a_soma_a_altura_da_tela():
    faixa, gameplay, camera = vertical.medidas_layout_a()
    assert faixa + gameplay + camera == config.VERTICAL_ALTURA
    assert faixa == 200
    assert camera == 576  # 30% de 1920
    assert all(v % 2 == 0 for v in (faixa, gameplay, camera))


def test_filtro_a_usa_camera_marcada():
    f = vertical.filtro("A", [0.7, 0.65, 0.28, 0.32])
    assert "vstack" in f
    assert "x=iw*0.70000" in f and "w=iw*0.28000" in f
    assert "pad=1080:1920:0:200" in f
    assert "fps=60" in f


def test_filtro_a_sem_camera_cai_para_c():
    assert vertical.filtro("A", None) == vertical.filtro_layout_c()
    assert vertical.filtro("A", [2, 0, 0.1, 0.1]) == vertical.filtro_layout_c()


def test_filtro_c_tem_fundo_desfocado():
    f = vertical.filtro("C")
    assert "boxblur" in f and "overlay" in f and "fps=60" in f


def test_comando_vertical_amf_e_cpu(tmp_path):
    amf = vertical.comando_vertical(tmp_path / "e.mp4", tmp_path / "s.mp4", "C", None, "amf")
    cpu = vertical.comando_vertical(tmp_path / "e.mp4", tmp_path / "s.mp4", "C", None, "cpu")
    assert "h264_amf" in amf and "libx264" in cpu
    assert "+faststart" in amf


# ---------------------------------------------------------------------
#  ajustes por canal
# ---------------------------------------------------------------------
def test_canal_sem_ajustes_usa_padrao(arquivo_canais):
    assert canais.obter("novo") == {"layout": config.LAYOUT_PADRAO, "camera": None}
    assert canais.layout_efetivo("novo") == "C"  # A sem câmera -> C


def test_definir_camera_e_layout(arquivo_canais):
    canais.definir("burn", camera=[0.1, 0.2, 0.3, 0.4], layout="A")
    assert canais.obter("burn")["camera"] == [0.1, 0.2, 0.3, 0.4]
    assert canais.layout_efetivo("burn") == "A"

    canais.definir("burn", layout="C")
    assert canais.layout_efetivo("burn") == "C"
    assert canais.obter("burn")["camera"] == [0.1, 0.2, 0.3, 0.4]  # câmera continua salva


def test_arquivo_corrompido_nao_quebra(arquivo_canais):
    arquivo_canais.write_text("{ isso não é json", encoding="utf-8")
    assert canais.obter("qualquer")["layout"] == config.LAYOUT_PADRAO


@pytest.mark.parametrize(
    ("camera", "valida"),
    [
        ([0, 0, 1, 1], True),
        ([0.5, 0.5, 0.5, 0.5], True),
        ([0.9, 0, 0.5, 0.5], False),  # passa da borda
        ([0, 0, 0, 0.5], False),  # largura zero
        ([0, 0, 1], False),
        ("abc", False),
        (None, False),
    ],
)
def test_camera_valida(camera, valida):
    assert canais.camera_valida(camera) is valida


# ---------------------------------------------------------------------
#  destino dos arquivos (vertical sempre; original só se configurado)
# ---------------------------------------------------------------------
@pytest.fixture
def ambiente_fila(tmp_path, monkeypatch, arquivo_canais):
    monkeypatch.setattr(config, "PASTA_VERTICAL", str(tmp_path / "vertical"))
    monkeypatch.setattr(config, "PASTA_ORIGINAIS", str(tmp_path / "originais"))
    temp = tmp_path / "proc" / "orig_burn_2026-11-18_10-00-00_risada.mp4"
    temp.parent.mkdir()
    temp.write_bytes(b"original")
    fila = vertical.FilaVertical.__new__(vertical.FilaVertical)  # sem a thread da fila
    trabalho = vertical.Trabalho("burn", "burn_2026-11-18_10-00-00_risada.mp4", temp)
    return fila, trabalho, tmp_path


def _vertical_falso(ok):
    def gerar(entrada, saida, layout, camera):
        if ok:
            saida.write_bytes(b"vertical")
        return ok

    return gerar


@pytest.mark.parametrize("salvar_originais", [True, False])
def test_vertical_e_original_conforme_configuracao(ambiente_fila, monkeypatch, salvar_originais):
    fila, trabalho, tmp = ambiente_fila
    monkeypatch.setattr(config, "SALVAR_ORIGINAIS", salvar_originais)
    monkeypatch.setattr(vertical, "gerar_vertical", _vertical_falso(True))

    assert fila._processar(trabalho)
    assert (tmp / "vertical" / "burn" / trabalho.nome).read_bytes() == b"vertical"
    assert (tmp / "originais" / "burn" / trabalho.nome).exists() is salvar_originais
    assert not trabalho.original_temp.exists()  # temporário nunca fica para trás


def test_original_salvo_se_o_vertical_falhar(ambiente_fila, monkeypatch):
    fila, trabalho, tmp = ambiente_fila
    monkeypatch.setattr(config, "SALVAR_ORIGINAIS", False)
    monkeypatch.setattr(vertical, "gerar_vertical", _vertical_falso(False))

    assert not fila._processar(trabalho)
    assert (tmp / "originais" / "burn" / trabalho.nome).read_bytes() == b"original"
