# Auto-Clipper de Lives (Twitch + YouTube + Kick)

Monitora lives da **Twitch**, do **YouTube** e do **Kick** em tempo real e, quando detecta um momento marcante — **risada, grito, explosão no jogo, fala mais alta ou pico no chat** — gera automaticamente um clipe de **3 minutos** (1 min antes + 2 min depois do momento) já no **formato vertical 9:16**, pronto para Reels, TikTok e Shorts. Tudo controlado por um **painel no navegador**.

Feito para lives de GTA em português, mas funciona com qualquer live.

> Tudo roda **100% local**, sem serviços pagos nem chaves de API.

---

## Como funciona

```
streamlink ──► ffmpeg ─┬─► buffer de pedaços de 10 s (23 min, sem recodificar)
                       └─► áudio 16 kHz ──► YAMNet + volume ──┐
chat (Twitch IRC / YouTube via yt-dlp) ──► ritmo de mensagens ─┴─► score (1x/s)
                                                                       │
            original 16:9 (corte sem recodificar) ◄── clipe ◄──────────┘
                     │
                     └─► fila ──► vertical 1080×1920 (placa AMD ou processador)
```

1. Cada live roda em sua própria thread. O vídeo é gravado em pedaços de 10 s num buffer circular, **sem recodificar** (`-c copy`), então quase não usa CPU.
2. A cada segundo o áudio é analisado pelo **[YAMNet](https://tfhub.dev/google/yamnet/1)** (modelo do Google que reconhece 521 tipos de som), rodando na CPU.
3. O volume é comparado com a **média do próprio streamer** (últimos 2 min), não com um valor fixo.
4. O chat é lido em paralelo: um pico de mensagens (ou muitas com `kkk`, `kekw`, `💀`...) aumenta o score. No **Kick** o chat não é lido (fica atrás de uma proteção anti-robô): a live é monitorada só pelo áudio.
5. Quando o score passa do limiar, os pedaços do buffer viram o **original 16:9**, e uma **fila** (um clipe por vez, para não atrapalhar a captura) gera o **vertical**.

### Score de detecção

```
evento    = maior probabilidade YAMNet entre {risada, grito, explosão}
volume    = 0 em +5 dB acima da média → 1 em +10 dB
chat      = 0 em 1,5x o ritmo normal → 1 em 4x (+0,3 se ≥30% das msgs têm palavras-chave)

score = 0,6·evento + 0,2·volume + 0,3·chat        → dispara se score ≥ 0,45
```

- Se **música** dominar o áudio, o evento é penalizado e o volume ignorado (evita falso positivo).
- Enquanto um clipe automático está sendo gravado, novas flags automáticas são ignoradas (cooldown). O **clipe manual** sempre gera.
- **Corte por tempo:** se passar 15 min sem nenhum clipe, corta o melhor momento do período (sai com o motivo `auto-por-tempo` no nome).

### Formato vertical (1080×1920, 60 fps)

| Layout | Como fica | Quando usar |
|---|---|---|
| **A** | Faixa vazia no topo (200 px, para escrever o título no app) · gameplay no meio (centro da live) · **câmera do streamer embaixo (30%)** | Streamer com câmera |
| **C** | Vídeo inteiro no centro, com o próprio vídeo **desfocado** no fundo | Sem câmera, ou câmera ainda não marcada |

O layout é escolhido **por canal** no painel. A posição da câmera é marcada uma vez: o painel pega um quadro da live e você arrasta um retângulo em cima da câmera. Um canal em A sem câmera marcada sai em C automaticamente.

A codificação usa a **placa de vídeo AMD (AMF)** quando disponível — bem mais rápida e quase sem uso de processador — e cai para o processador (`libx264`) se a placa falhar.

### Robustez

- Reconecta sozinho se a live cair ou estiver offline (tenta a cada 30 s).
- Watchdog: 60 s sem áudio → reinicia a captura.
- Os arquivos são gerados fora da pasta final e só depois movidos (seguro para pastas sincronizadas como Google Drive).
- Depois de uma pausa, um clipe nunca junta trechos de antes e depois da pausa.
- No Windows, os programas abertos (streamlink, yt-dlp, ffmpeg) ficam num *Job Object*: se o Auto-Clipper fechar — até pelo X da janela — eles fecham juntos, sem processos órfãos.

---

## Requisitos

- Windows 10/11 (testado no Windows 11)
- **Python 3.10 a 3.12** (o TensorFlow ainda não suporta versões mais novas)
- **ffmpeg**
- Placa de vídeo AMD é opcional (acelera o vertical)

## Instalação

```powershell
winget install Python.Python.3.12
winget install Gyan.FFmpeg
```

Feche e abra o terminal, depois, na raiz do projeto:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

O `-e` instala o pacote em modo editável: mudanças no código valem sem reinstalar.

## Configuração

Os valores padrão ficam em [`src/autoclipper/config.py`](src/autoclipper/config.py). Seus dados (links das lives e pastas) vão num arquivo **`config_local.py`**, que fica fora do Git. Crie-o na raiz do projeto:

```python
# config_local.py — qualquer valor aqui substitui o de config.py
LINKS_DAS_LIVES = [
    "https://www.twitch.tv/CANAL",
    "https://www.youtube.com/live/ID_DO_VIDEO",
]

PASTA_CLIPES = r"G:\Meu Drive\Clipes"  # Google Drive para desktop → acesso pelo celular

# originais 16:9: padrão é <PASTA_CLIPES>\originais; para salvar no PC:
# PASTA_ORIGINAIS = r"C:\clipes\originais"
```

Estrutura gerada:

```
<PASTA_CLIPES>\
├── vertical\<canal>\    ← 9:16 para postar
└── originais\<canal>\   ← 16:9 na qualidade da live (sem recodificar)
```

O vertical e o original do mesmo momento têm o **mesmo nome**: `<canal>_<data>_<hora>_<motivo>.mp4`, onde o motivo é `risada`, `grito`, `explosao`, `volume`, `chat`, `manual` ou `auto-por-tempo`.

**Google Drive (opcional):** instale o [Google Drive para desktop](https://www.google.com/drive/download/) (`winget install Google.GoogleDrive`), faça login e aponte `PASTA_CLIPES` para uma pasta dentro de `G:\Meu Drive`.

| Parâmetro | Padrão | O que faz |
|---|---|---|
| `LIMIAR_SCORE` | `0.45` | Sensibilidade. Muito clipe ruim → aumente (0.55). Pouco clipe → diminua (0.40) |
| `SEGUNDOS_ANTES` / `SEGUNDOS_DEPOIS` | `60` / `120` | Duração do clipe em volta do momento |
| `CORTE_FORCADO_MINUTOS` | `15` | Tempo máximo sem clipe antes do corte por tempo |
| `QUALIDADE` | `"best"` | Qualidade da captura (`"720p60"` alivia disco e banda) |
| `LAYOUT_PADRAO` | `"A"` | Layout dos canais novos |
| `FAIXA_TOPO_PX` / `CAMERA_PCT` | `200` / `0.30` | Faixa vazia do topo e altura da câmera no layout A |
| `VERTICAL_FPS` / `VERTICAL_BITRATE` | `60` / `"10M"` | Qualidade do vertical |
| `CODIFICADOR` | `"auto"` | `"auto"` (placa AMD se houver), `"amf"` ou `"cpu"` |
| `SALVAR_ORIGINAIS` | `True` | `False` salva só o vertical (ocupa bem menos espaço). Se o vertical falhar, o original é salvo mesmo assim |
| `PALAVRAS_CHAT` | `kkk, kekw, ...` | Palavras que indicam reação no chat |
| `INTERVALO_LOG_SCORE` | `15` | Loga o maior score a cada N s, para calibrar (0 = desliga) |
| `LOG_MAX_MB` / `LOG_BACKUPS` | `5` / `3` | Rotação do log |
| `ACESSO_REMOTO` | `False` | `True` publica o painel na sua rede Tailscale (acesso pelo celular) |

## Uso

### Painel (recomendado)

Dê dois cliques em **`Abrir painel.bat`** (ou rode `.\.venv\Scripts\python.exe -m autoclipper.painel`). O painel abre no navegador em `http://localhost:8501` assim que estiver pronto; se ele já estiver aberto, o atalho só abre a página. A janela preta que abre junto é o motor: **minimize, não feche**. Para desligar, use **⏻ Encerrar tudo** no painel.

```
┌──────────────────────────────────────────────────────────────────────────┐
│ 🎬 Auto-Clipper   [▶ Iniciar todas] [⏹ Finalizar todas] [⏻ Encerrar tudo] │
│ Lives ativas 3 de 3 · Clipes hoje 7 · Espaço livre · Na fila   │
├────────────────────────────────────────────────────────────────┤
│ burn · Twitch     🟢 Ao vivo         [✂ Clipar] [⏸ Pausar] [⏹]  │
│ rodil · Twitch    ⏸ Pausada          [▶ Retomar] [⏹ Finalizar]  │
│ 🔗 Lives monitoradas: [link da live…] [➕ Adicionar] · [🗑 Remover] │
├────────────────────────────────────────────────────────────────┤
│ Últimos clipes: hora · canal · motivo · score · [▶] [📁]        │
│ 🗑 Apagar clipes com mais de N dias                             │
│ ⚙ Configuração: layout A/C por canal · [🎯 Marcar câmera]       │
└────────────────────────────────────────────────────────────────┘
```

| Botão | O que faz |
|---|---|
| **Encerrar tudo** | Finaliza as lives, termina os clipes pendentes, confere que nenhum programa (captura, chat, ffmpeg) ficou aberto e fecha o painel |
| **Finalizar todas** | Para todas as lives, mas o painel continua aberto |
| **Clipar** | Clipe manual: `SEGUNDOS_ANTES` antes + `SEGUNDOS_DEPOIS` depois do clique. Sempre gera, mesmo com outro clipe em andamento |
| **Pausar** | Desliga captura, análise e chat daquela live (zero CPU e banda) até **Retomar** |
| **Finalizar** | Desconecta e apaga o buffer daquela live |
| **Apagar clipes antigos** | Mostra quantos arquivos (vertical + original) serão apagados e pede confirmação |
| **Marcar câmera** | Abre um quadro da live numa janela: arraste o retângulo sobre a câmera e aperte ENTER |
| **🔗 Lives monitoradas** | Adiciona ou remove lives **sem reiniciar**: cole o link (Twitch, YouTube ou Kick) e aperte Adicionar. Remover finaliza a live antes, sem perder os clipes pendentes |

A lista começa com o `LINKS_DAS_LIVES` do `config_local.py`. Depois da primeira mudança pelo painel, ela fica salva em `lives.json` (fora do Git), que passa a valer no lugar do `LINKS_DAS_LIVES`. Para voltar a usar o `config_local.py`, apague o `lives.json`.

### Pelo celular (Tailscale)

O painel pode ser controlado do celular, de qualquer lugar, sem abrir nada na internet: o [Tailscale](https://tailscale.com/) cria uma rede privada entre os seus aparelhos, e só eles enxergam o painel.

1. Instale o Tailscale no PC (`winget install Tailscale.Tailscale`) e no celular (App Store / Play Store) e entre com **a mesma conta** nos dois.
2. No `config_local.py`, coloque `ACESSO_REMOTO = True`.
3. Abra o painel pelo atalho. Ele roda `tailscale serve` e mostra o endereço no rodapé, algo como `http://seu-pc.tailXXXX.ts.net`.
4. No celular, ligue o app Tailscale e abra esse endereço no navegador (dá para salvar na tela de início).

O painel continua escutando só em `localhost`; o Tailscale repassa o acesso apenas para os aparelhos da sua conta (`tailnet only`), com o tráfego criptografado. Para desligar a publicação: `tailscale serve reset`.

> O PC precisa ficar ligado e sem suspender. **Encerrar tudo** pelo celular desliga o painel, e ele só volta abrindo o atalho no PC. Os botões ▶ e 📁 dos clipes abrem o arquivo na tela do PC; para ver o clipe no celular, use o app do Google Drive.

### Terminal

```powershell
.\.venv\Scripts\python.exe -m autoclipper
```

Inicia todas as lives; `Ctrl+C` para parar. O log fica em `autoclipper.log`:

```
21:30:12 [canal] FLAG! motivo=risada score=0.62 momento=21:30:02 - gerando clipe...
21:32:19 [canal] Clipe cortado, na fila do vertical: canal_2026-11-18_21-30-02_risada.mp4
21:33:40 [canal] CLIPE SALVO (layout A): ...\vertical\canal\canal_2026-11-18_21-30-02_risada.mp4
```

### Calibrando

As linhas `[calib]` mostram o maior score de cada período e o que pesou nele:

```
[calib] max=0.47 | explosao=0.70 vol=0.00 (db=-23.8 base=-26.0) musica=0.08 chat=0.00
```

Compare com os momentos que você achou bons na live e ajuste `LIMIAR_SCORE`.

---

## Estrutura

```
src/autoclipper/
├── __main__.py       # modo terminal (python -m autoclipper)
├── painel.py         # abre o painel (python -m autoclipper.painel)
├── painel_app.py     # página do painel (Streamlit)
├── gerenciador.py    # comandos e status de todas as lives (usado pelo painel e terminal)
├── monitor.py        # MonitorLive: captura, buffer, análise, pausa, clipe manual
├── vertical.py       # layouts 9:16, codificador (AMF/CPU) e fila de processamento
├── canais.py         # layout e câmera por canal (canais.json)
├── lives.py          # lista de lives editada pelo painel (lives.json)
├── marcar_camera.py  # janela para marcar a câmera do streamer
├── detector.py       # DetectorAudio (YAMNet) + volume em dB
├── chat.py           # LeitorChat: Twitch (IRC anônimo) e YouTube (yt-dlp)
├── remoto.py         # publica o painel na rede Tailscale (acesso pelo celular)
├── sistema.py        # log com rotação e PATH do ffmpeg
└── config.py         # valores padrão de todos os parâmetros
tests/                # testes automatizados (pytest)
Abrir painel.bat      # atalho de dois cliques para o painel
config_local.py       # seus links e pastas (fora do Git)
canais.json           # layout e câmera por canal, gravado pelo painel (fora do Git)
lives.json            # lista de lives, gravada pelo painel (fora do Git)
pyproject.toml        # metadados, dependências e configuração do Ruff e do pytest
```

## Desenvolvimento

Instale as ferramentas de desenvolvimento ([Ruff](https://docs.astral.sh/ruff/) e [pytest](https://docs.pytest.org/)):

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

```powershell
.\.venv\Scripts\python.exe -m pytest            # testes
.\.venv\Scripts\python.exe -m ruff check .      # lint
.\.venv\Scripts\python.exe -m ruff format .     # formatação
```

Os testes não precisam de live, ffmpeg nem do modelo YAMNet: cobrem a leitura dos links, o parser do chat do YouTube, o score do chat, o cálculo de volume, o `config_local.py`, os filtros dos layouts A e C, os ajustes por canal, os nomes dos clipes, a seleção de trechos depois de uma pausa, a limpeza de clipes antigos, a publicação no Tailscale e a lista de lives editável pelo painel.

## Stack

| Função | Ferramenta |
|---|---|
| Captura da live | [streamlink](https://streamlink.github.io/) · [yt-dlp](https://github.com/yt-dlp/yt-dlp) |
| Buffer, corte e vertical | [ffmpeg](https://ffmpeg.org/) (AMD AMF ou libx264) |
| Detecção de áudio | [YAMNet](https://tfhub.dev/google/yamnet/1) (TensorFlow Hub) |
| Chat Twitch | IRC anônimo (`irc.chat.twitch.tv`) |
| Chat YouTube | yt-dlp (`--sub-langs live_chat`) |
| Kick | streamlink (captura); chat não suportado |
| Painel | [Streamlit](https://streamlit.io/) |
| Marcar câmera | [OpenCV](https://opencv.org/) |
| Acesso pelo celular | [Tailscale](https://tailscale.com/) (`tailscale serve`) |

---

## Roadmap

- **Início automático com o Windows:** o painel sobe sozinho quando o PC liga, para poder religar tudo pelo celular.

## Observações

- **Direitos autorais:** postar clipes de outros criadores pode gerar strike. Tenha permissão do streamer ou participe de um programa oficial de clipes.
- **Desempenho:** cada live usa ~2 GB de disco de buffer. Cada clipe gera ~225 MB (vertical) + ~135 MB (original).
- YouTube muda com frequência: se a captura ou o chat pararem, atualize com `pip install -U yt-dlp streamlink`.

## Licença

[MIT](LICENSE)
