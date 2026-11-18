"""Página do painel (Streamlit). Abra com:  python -m autoclipper.painel

O motor (Gerenciador) é criado uma vez só e continua rodando mesmo se a aba do
navegador for fechada ou recarregada; ele só para com o botão "Encerrar tudo"
ou quando a janela do painel (o terminal minimizado) for fechada.
"""

from autoclipper.sistema import silenciar_tensorflow

silenciar_tensorflow()

import os
import subprocess
import sys
import threading

import streamlit as st
import streamlit.components.v1 as components

from autoclipper import canais, config
from autoclipper.gerenciador import Gerenciador
from autoclipper.monitor import AO_VIVO, CONECTANDO, OFFLINE, PARADA, PAUSADA
from autoclipper.sistema import configurar_log, garantir_ffmpeg

st.set_page_config(page_title="Auto-Clipper", page_icon="🎬", layout="centered")

ROTULOS = {
    AO_VIVO: "🟢 Ao vivo",
    CONECTANDO: "🔵 Conectando…",
    OFFLINE: "🔴 Offline, tentando reconectar…",
    PAUSADA: "⏸️ Pausada",
    PARADA: "⚪ Parada",
}
MOTIVOS = {
    "risada": "😂 risada",
    "grito": "😱 grito",
    "explosao": "💥 explosão",
    "volume": "🔊 volume",
    "chat": "💬 chat",
    "manual": "✂️ manual",
    config.MOTIVO_POR_TEMPO: "⏱️ por tempo",
}


@st.cache_resource(show_spinner=False)
def motor() -> Gerenciador:
    configurar_log(no_terminal=True)
    garantir_ffmpeg()
    return Gerenciador()


@st.cache_data(ttl=300, show_spinner=False)
def endereco_celular() -> str | None:
    from autoclipper import remoto

    return remoto.endereco_remoto(config.PORTA_REMOTA)


def abrir_arquivo(caminho):
    if sys.platform == "win32":
        os.startfile(caminho)  # abre no player padrão do Windows


def abrir_pasta(caminho):
    if sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", str(caminho)])


g = motor()

# =====================================================================
#  CABEÇALHO
# =====================================================================
col_titulo, col_ini, col_fim, col_sair = st.columns(
    [1.6, 1.25, 1.25, 1.25], vertical_alignment="center"
)
col_titulo.markdown("### 🎬&nbsp;Auto&#8209;Clipper")  # espaço e hífen que não quebram
if col_ini.button("▶ Iniciar todas", use_container_width=True, disabled=not g.monitores):
    with st.spinner("Carregando o modelo de áudio e conectando nas lives…"):
        g.iniciar_todas()
if col_fim.button(
    "⏹ Finalizar todas",
    use_container_width=True,
    disabled=not g.monitores,
    help="Para todas as lives, mas o painel continua aberto",
):
    g.finalizar_todas()
    st.toast("Todas as lives foram finalizadas.")
if col_sair.button(
    "⏻ Encerrar tudo",
    use_container_width=True,
    help="Fecha o Auto-Clipper inteiro e confere que nada ficou rodando",
):
    st.session_state["confirmar_encerrar"] = True


def encerrar_tudo():
    """Desliga tudo, mostra o resultado e fecha o painel (e a janela preta)."""
    andamento = st.empty()
    with st.spinner("Encerrando…"):
        resumo = g.encerrar_tudo(progresso=lambda msg: andamento.info(msg))
    andamento.empty()

    abertos = resumo["processos_abertos"]
    if abertos == 0:
        st.success(
            "✅ **Tudo encerrado.** Nenhum programa do Auto-Clipper ficou aberto "
            "(captura, chat e ffmpeg conferidos). Pode fechar esta aba."
        )
    elif abertos is None:
        st.success("✅ Lives finalizadas e fila concluída. Pode fechar esta aba.")
        st.caption("Não deu para conferir os programas abertos (painel aberto sem o atalho).")
    else:
        st.error(
            f"⚠️ {abertos} programa(s) não fecharam nem à força. Feche a janela preta "
            "do Auto-Clipper para encerrar o resto."
        )
    if resumo["forcados"]:
        st.caption(f"{resumo['forcados']} programa(s) precisaram ser fechados à força.")
    if resumo["fila_restante"]:
        st.warning(
            f"{resumo['fila_restante']} clipe(s) não terminaram de converter a tempo; "
            "os originais ficaram em buffer\\_processando."
        )
    # troca a página por uma tela final (em vez do aviso "Connection error" do
    # Streamlit) e desliga o servidor do painel; a janela preta fecha junto
    texto = "Nenhum programa ficou aberto." if abertos == 0 else "Lives finalizadas."
    components.html(
        f"""<script>
        setTimeout(() => {{
          const d = window.parent.document;
          d.title = "Auto-Clipper encerrado";
          d.body.innerHTML = `<div style="font-family:sans-serif;background:#0e1117;
            color:#fafafa;height:100vh;display:flex;flex-direction:column;
            align-items:center;justify-content:center;gap:12px">
            <div style="font-size:48px">✅</div>
            <div style="font-size:24px;font-weight:600">Auto-Clipper encerrado</div>
            <div style="color:#a3a8b8">{texto} Pode fechar esta aba.</div>
            <div style="color:#6b7080;font-size:13px">Para abrir de novo, use o atalho
            Auto-Clipper na Área de Trabalho.</div></div>`;
        }}, 2000);
        </script>""",
        height=0,
    )
    threading.Timer(3, lambda: os._exit(0)).start()
    st.stop()


if st.session_state.get("confirmar_encerrar"):
    with st.container(border=True):
        pendentes = sum(s["pendentes"] for s in g.status())
        st.warning(
            "**Encerrar tudo?** As lives são finalizadas, os clipes pendentes "
            f"({pendentes}) são terminados e o painel fecha."
            + (
                " **Pelo celular não dá para religar depois:** só abrindo o atalho no PC."
                if config.ACESSO_REMOTO
                else ""
            )
        )
        sim, nao = st.columns(2)
        if sim.button("Sim, encerrar tudo", type="primary", use_container_width=True):
            st.session_state.pop("confirmar_encerrar", None)
            encerrar_tudo()
        if nao.button("Cancelar", use_container_width=True):
            st.session_state.pop("confirmar_encerrar", None)
            st.rerun()

if not g.monitores:
    st.warning(
        "Nenhuma live configurada. Coloque os links em `LINKS_DAS_LIVES` no arquivo "
        f"`{config.ARQUIVO_CONFIG_LOCAL}` e reabra o painel."
    )
    st.stop()


# =====================================================================
#  RESUMO + LIVES (atualiza sozinho a cada 2 s)
# =====================================================================
@st.fragment(run_every=2)
def lives():
    status = g.status()
    ativas = sum(1 for s in status if s["estado"] in (AO_VIVO, CONECTANDO, OFFLINE))
    livre = g.espaco_livre_gb()

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Lives ativas", f"{ativas} de {len(status)}")
    m2.metric("Clipes hoje", g.clipes_hoje())
    m3.metric("Espaço livre", f"{livre:.1f} GB" if livre is not None else "—")
    m4.metric("Na fila", g.fila.tamanho(), help="Clipes sendo convertidos para vertical")

    st.markdown("#### Lives")
    for s in status:
        canal, estado = s["canal"], s["estado"]
        with st.container(border=True):
            info, acoes = st.columns([1.6, 2.4], vertical_alignment="center")
            rotulo = ROTULOS.get(estado, estado)
            if s["pendentes"]:
                rotulo += f"  ·  🟡 gerando {s['pendentes']} clipe(s)…"
            info.markdown(f"**{canal}** · {s['plataforma'].capitalize()}  \n{rotulo}")
            info.caption(f"clipes nesta sessão: {s['clipes_sessao']}")

            b1, b2, b3 = acoes.columns(3)
            if estado in (AO_VIVO, CONECTANDO, OFFLINE):
                if b1.button(
                    "✂️ Clipar",
                    key=f"clip_{canal}",
                    use_container_width=True,
                    disabled=estado != AO_VIVO,
                    help=(
                        f"Clipe manual: {config.SEGUNDOS_ANTES} s antes + "
                        f"{config.SEGUNDOS_DEPOIS} s depois de agora"
                    ),
                ):
                    ok, msg = g.clipar(canal)
                    st.toast(f"{canal}: {msg}")
                if b2.button("⏸️ Pausar", key=f"pausa_{canal}", use_container_width=True):
                    g.pausar(canal)
                    st.rerun(scope="fragment")
                if b3.button("⏹️ Finalizar", key=f"fim_{canal}", use_container_width=True):
                    g.finalizar(canal)
                    st.rerun(scope="fragment")
            elif estado == PAUSADA:
                if b1.button("▶️ Retomar", key=f"ret_{canal}", use_container_width=True):
                    g.retomar(canal)
                    st.rerun(scope="fragment")
                if b2.button("⏹️ Finalizar", key=f"fim_{canal}", use_container_width=True):
                    g.finalizar(canal)
                    st.rerun(scope="fragment")
            elif b1.button("▶️ Iniciar", key=f"ini_{canal}", use_container_width=True):
                with st.spinner("Conectando…"):
                    g.iniciar(canal)
                st.rerun(scope="fragment")


lives()


# =====================================================================
#  ÚLTIMOS CLIPES (atualiza a cada 5 s)
# =====================================================================
@st.fragment(run_every=5)
def ultimos_clipes():
    st.markdown("#### Últimos clipes")
    clipes = g.listar_clipes(limite=10)
    if not clipes:
        st.caption("Nenhum clipe ainda. Eles aparecem aqui assim que o vertical fica pronto.")
        return
    for c in clipes:
        hora, canal, motivo, score, assistir, pasta = st.columns(
            [1.1, 1.8, 1.5, 0.7, 0.7, 0.7], vertical_alignment="center"
        )
        hora.write(c.momento[11:16])
        canal.write(c.canal)
        motivo.write(MOTIVOS.get(c.motivo, c.motivo))
        score.write(f"{c.score:.2f}" if c.score is not None else "—")
        if assistir.button("▶", key=f"ver_{c.caminho}", help="Assistir (vertical)"):
            abrir_arquivo(c.caminho)
        if pasta.button("📁", key=f"pasta_{c.caminho}", help="Abrir a pasta"):
            abrir_pasta(c.caminho)


ultimos_clipes()

# =====================================================================
#  APAGAR CLIPES ANTIGOS
# =====================================================================
with st.container(border=True):
    st.markdown("**🗑️ Apagar clipes antigos** (vertical e original)")
    c_dias, c_ver = st.columns([1, 2], vertical_alignment="bottom")
    dias = c_dias.number_input("Mais de quantos dias", min_value=1, max_value=365, value=7)
    if c_ver.button("Ver quantos serão apagados", use_container_width=True):
        st.session_state["para_apagar"] = (dias, len(g.clipes_antigos(dias)))

    pendente = st.session_state.get("para_apagar")
    if pendente and pendente[0] == dias:
        qtd = pendente[1]
        if qtd == 0:
            st.info(f"Nenhum clipe com mais de {dias} dia(s).")
        else:
            st.warning(
                f"{qtd} arquivo(s) com mais de {dias} dia(s) serão apagados. "
                "No Google Drive eles vão para a lixeira (dá para recuperar por 30 dias)."
            )
            if st.button(f"Confirmar: apagar {qtd} arquivo(s)", type="primary"):
                apagados = g.apagar_clipes_antigos(dias)
                st.session_state.pop("para_apagar", None)
                st.success(f"{apagados} arquivo(s) apagado(s).")

# =====================================================================
#  CONFIGURAÇÃO DAS LIVES
# =====================================================================
with st.expander("⚙️ Configuração das lives (layout do vertical e câmera)"):
    st.caption(
        "**A**: faixa vazia no topo + gameplay + câmera do streamer embaixo (30%).  \n"
        "**C**: vídeo inteiro no centro com fundo desfocado (não precisa marcar câmera).  \n"
        "Um canal em A sem câmera marcada sai em C até você marcar."
    )
    for m in g.monitores:
        ajustes = canais.obter(m.canal)
        col_nome, col_layout, col_cam = st.columns([1.4, 1.6, 1.6], vertical_alignment="center")
        col_nome.markdown(f"**{m.canal}**")
        escolhido = col_layout.radio(
            "Layout",
            canais.LAYOUTS,
            index=canais.LAYOUTS.index(ajustes["layout"]),
            key=f"layout_{m.canal}",
            horizontal=True,
            label_visibility="collapsed",
        )
        if escolhido != ajustes["layout"]:
            canais.definir(m.canal, layout=escolhido)
            st.toast(f"{m.canal}: layout {escolhido}")
        situacao = "✅ câmera marcada" if ajustes["camera"] else "câmera não marcada"
        if col_cam.button("🎯 Marcar câmera", key=f"cam_{m.canal}", help=situacao):
            subprocess.Popen(
                [sys.executable, "-m", "autoclipper.marcar_camera", m.canal, m.url],
                cwd=str(config.PASTA_BASE),
            )
            st.info(
                f"Abrindo uma janela na tela do PC com um quadro de {m.canal}. "
                "Arraste um retângulo em cima da câmera e aperte ENTER (ESC cancela)."
            )
        col_cam.caption(situacao)

originais = config.PASTA_ORIGINAIS if config.SALVAR_ORIGINAIS else "não são salvos"
st.caption(f"Clipes: {config.PASTA_VERTICAL}  ·  Originais 16:9: {originais}")
if config.ACESSO_REMOTO:
    remoto_url = endereco_celular()
    st.caption(
        f"📱 Pelo celular (app Tailscale ligado): {remoto_url}"
        if remoto_url
        else "📱 Acesso pelo celular indisponível (Tailscale desligado?)"
    )
