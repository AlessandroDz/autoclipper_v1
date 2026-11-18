# Auto-Clipper de Lives (Twitch + YouTube)

Monitora lives da **Twitch** e do **YouTube** em tempo real e, quando detecta um momento marcante — **risada, grito, explosão no jogo, fala mais alta ou pico no chat** — gera automaticamente um clipe de **3 minutos** (1 min antes + 2 min depois do momento), pronto para virar Reels, TikTok ou Shorts.

Feito para lives de GTA em português, mas funciona com qualquer live.

> **Status:** v1 — captura, detecção e corte funcionando em lives reais. Calibração da sensibilidade em andamento. Formato vertical e painel estão no [roadmap](#roadmap).
>
> Tudo roda **100% local**, sem serviços pagos nem chaves de API.

---

## Como funciona

```
streamlink ──► ffmpeg ─┬─► buffer de pedaços de 10 s (23 min, sem recodificar)
                       └─► áudio 16 kHz ──► YAMNet + volume ──┐
chat (Twitch IRC / YouTube via yt-dlp) ──► ritmo de mensagens ─┴─► score (1x/s) ──► clipe
```

1. Cada live roda em sua própria thread. O vídeo é gravado em pedaços de 10 s num buffer circular, **sem recodificar** (`-c copy`), então quase não usa CPU.
2. A cada segundo o áudio é analisado pelo **[YAMNet](https://tfhub.dev/google/yamnet/1)** (modelo do Google que reconhece 521 tipos de som), rodando na CPU.
3. O volume é comparado com a **média do próprio streamer** (últimos 2 min), não com um valor fixo.
4. O chat é lido em paralelo: um pico de mensagens (ou muitas com `kkk`, `kekw`, `💀`...) aumenta o score.
5. Quando o score passa do limiar, os pedaços do buffer são juntados num `.mp4`.

### Score de detecção

```
evento    = maior probabilidade YAMNet entre {risada, grito, explosão}
volume    = 0 em +6 dB acima da média → 1 em +12 dB
chat      = 0 em 1,5x o ritmo normal → 1 em 4x (+0,3 se ≥30% das msgs têm palavras-chave)

score = 0,6·evento + 0,2·volume + 0,3·chat        → dispara se score ≥ 0,55
```

- Uma risada forte sozinha já dispara; volume + chat sem nenhum evento, não.
- Se **música** dominar o áudio, o evento é penalizado e o volume ignorado (evita falso positivo).
- Enquanto um clipe está sendo gravado, novas flags são ignoradas (cooldown).
- **Corte forçado:** se passar 20 min sem nenhum clipe, corta o melhor momento do período.

### Robustez

- Reconecta sozinho se a live cair ou estiver offline (tenta a cada 30 s).
- Watchdog: 60 s sem áudio → reinicia a captura.
- O clipe é gerado fora da pasta final e só depois movido (seguro para pastas sincronizadas como Google Drive).

---

## Requisitos

- Windows 10/11 (testado no Windows 11)
- **Python 3.10 a 3.12** (o TensorFlow ainda não suporta versões mais novas)
- **ffmpeg**
- Não precisa de GPU

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

Os valores padrão ficam em [`src/autoclipper/config.py`](src/autoclipper/config.py). Seus dados (links das lives e pasta dos clipes) vão num arquivo **`config_local.py`**, que fica fora do Git. Crie-o na raiz do projeto:

```python
# config_local.py — qualquer valor aqui substitui o de config.py
LINKS_DAS_LIVES = [
    "https://www.twitch.tv/CANAL",
    "https://www.youtube.com/live/ID_DO_VIDEO",
]

PASTA_CLIPES = r"G:\Meu Drive\videos"  # Google Drive para desktop → acesso pelo celular
```

Sem `config_local.py`, os clipes vão para a pasta `videos` dentro do projeto.

**Google Drive (opcional):** instale o [Google Drive para desktop](https://www.google.com/drive/download/) (`winget install Google.GoogleDrive`), faça login e aponte `PASTA_CLIPES` para uma pasta dentro de `G:\Meu Drive`. O clipe é gerado fora do Drive e só movido quando está pronto, então o Drive nunca sincroniza um arquivo pela metade.

| Parâmetro | Padrão | O que faz |
|---|---|---|
| `LIMIAR_SCORE` | `0.55` | Sensibilidade. Muito clipe ruim → aumente (0.65). Pouco clipe → diminua (0.45) |
| `SEGUNDOS_ANTES` / `SEGUNDOS_DEPOIS` | `60` / `120` | Duração do clipe em volta do momento |
| `CORTE_FORCADO_MINUTOS` | `20` | Tempo máximo sem clipe antes do corte forçado |
| `QUALIDADE` | `"best"` | Qualidade da captura (`"720p60"` alivia disco e banda) |
| `PALAVRAS_CHAT` | `kkk, kekw, ...` | Palavras que indicam reação no chat |
| `INTERVALO_LOG_SCORE` | `15` | Loga o maior score a cada N s, para calibrar (0 = desliga) |
| `LOG_MAX_MB` / `LOG_BACKUPS` | `5` / `3` | Rotação do log: ao chegar em 5 MB vira `.1`, `.2`, `.3` e o mais antigo é apagado |

## Uso

Na raiz do projeto:

```powershell
.\.venv\Scripts\python.exe -m autoclipper
```

Com o venv ativado (`.\.venv\Scripts\Activate.ps1`), basta `autoclipper`. `Ctrl+C` para parar. No terminal (e em `autoclipper.log`):

```
23:30:12 [canal] FLAG! motivo=risada score=0.62 momento=23:30:02 - gerando clipe...
23:32:19 [canal] CLIPE SALVO: ...\canal\canal_2026-11-17_23-30-02_risada.mp4
```

Os clipes ficam em `PASTA_CLIPES\<canal>\<canal>_<data-hora>_<motivo>.mp4`, onde o motivo é `risada`, `grito`, `explosao`, `volume`, `chat` ou `forcado`.

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
├── __main__.py     # ponto de entrada (python -m autoclipper) + log com rotação
├── config.py       # valores padrão de todos os parâmetros
├── monitor.py      # MonitorLive: captura, buffer, análise, clipe e limpeza (iniciar()/parar())
├── detector.py     # DetectorAudio (YAMNet) + volume em dB
└── chat.py         # LeitorChat: Twitch (IRC anônimo) e YouTube (yt-dlp)
tests/              # testes automatizados (pytest)
config_local.py     # seus links e pastas (fora do Git)
pyproject.toml      # metadados, dependências e configuração do Ruff e do pytest
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

Os testes não precisam de live, ffmpeg nem do modelo YAMNet: cobrem a leitura dos links, o parser do chat do YouTube, o score do chat, o cálculo de volume e o carregamento do `config_local.py`.

## Stack

| Função | Ferramenta |
|---|---|
| Captura da live | [streamlink](https://streamlink.github.io/) · [yt-dlp](https://github.com/yt-dlp/yt-dlp) |
| Buffer e corte | [ffmpeg](https://ffmpeg.org/) |
| Detecção de áudio | [YAMNet](https://tfhub.dev/google/yamnet/1) (TensorFlow Hub) |
| Chat Twitch | IRC anônimo (`irc.chat.twitch.tv`) |
| Chat YouTube | yt-dlp (`--sub-langs live_chat`) |

---

## Roadmap

- **v2 — Vertical 9:16 (1080×1920):** layout dividido (gameplay em cima, câmera do streamer embaixo, posição da câmera configurável por canal) ou, sem câmera, o vídeo inteiro centralizado com fundo desfocado. Corte preciso com recodificação.
- **v3 — Painel Streamlit:** Start/Stop por live, status, layout e idioma por canal, lista dos últimos clipes.

## Observações

- **Direitos autorais:** postar clipes de outros criadores pode gerar strike. Tenha permissão do streamer ou participe de um programa oficial de clipes.
- **Desempenho:** 2 lives rodam tranquilo na CPU. Cada live usa ~2 GB de disco de buffer.
- YouTube muda com frequência: se a captura ou o chat pararem, atualize com `pip install -U yt-dlp streamlink`.

## Licença

[MIT](LICENSE)
