# Radar Operacional

Motor de alertas e boletins operacionais. **Etapa 1 (MVP local):** lê o BigQuery, detecta CDs novas,
gera uma prévia em HTML e registra tudo cifrado em SQLite. Ainda não envia nada para ninguém.

## Instalação (Windows)

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m radar init-keys        # gera e guarda as chaves no Credential Manager
```

Autenticação do BigQuery: `gcloud auth application-default login` (ou a conta de serviço da máquina).
Ajuste `bigquery.job_project` em `config/settings.yaml` para o projeto onde você tem permissão de rodar jobs.

## Comandos

| Comando | O que faz |
|---|---|
| `python -m radar listar` | Lista as tarefas |
| `python -m radar run demo` | Testa o fluxo com dados **fictícios** (sem BigQuery) |
| `python -m radar custo cds_novas_do_dia` | Estima os bytes lidos (dry_run do BigQuery) |
| `python -m radar run cds_novas_do_dia` | Dry-run: gera a prévia, **não** grava estado |
| `python -m radar run cds_novas_do_dia --real --forcar-inativa` | Grava snapshot e estado de alertas |
| `python -m radar run <tarefa> --todos` | Prévia com todos os itens, não só os novos |
| `python -m radar guardar-segredo teams_webhook_teste` | Guarda a URL do webhook no Credential Manager (pede sem mostrar) |
| `python -m radar teams-teste teste` | Envia uma mensagem de teste (sem dado operacional) ao canal |
| `python -m radar run demo_teams --real` | Fluxo completo com dados fictícios, publicando no Teams |
| `python -m radar historico` | Últimas execuções |
| `python -m radar limpar` | Aplica retenção (mensagens e previews) |
| `pytest` | Roda os testes |

## Estrutura

```
radar/
  storage/   crypto.py (Fernet + índice cego) e db.py (único lugar com SQL)
  sources/   bigquery.py, demo.py
  channels/  preview.py (HTML local). Futuros: teams_webhook, sharepoint, email
  engine/    runner.py (fonte -> índice cego -> novos -> mensagem -> canal -> log)
  templates/ preview.html.j2
config/      settings.yaml
sql/         cds_novas_do_dia.sql   (consulta original, sem alterações)
tasks/       uma tarefa por YAML
tests/       pytest, com dados fictícios
data/        SQLite e previews (fora do git)
```

## Decisões de projeto

- **Tudo é uma tarefa** (YAML): fonte, modo, mensagem, audiência, canais. Nova tarefa = novo YAML (e novo SQL).
- **Dry-run por padrão.** Só `--real` grava o estado "já avisei".
- **Anti-repetição:** a chave do item (`Nota`) vira um HMAC-SHA256 (índice cego). O banco compara hashes e nunca vê o valor.
- **Cifrado no banco:** conteúdo das mensagens e dos itens. **Em claro:** ids internos, datas, status, contagens, código de erro.
- **Chaves:** Credential Manager (`keyring`). Duas chaves distintas (cifragem e HMAC). `MultiFernet` permite rotação.
  **Faça backup das chaves separado do banco: sem elas o histórico é irrecuperável.**
- **Logs:** só códigos e tipos de erro, nunca conteúdo.
- **Previews em HTML** contêm dado operacional: ficam em `data/preview_tmp/`, com retenção de 24 h (`radar limpar`).
- **Sandbox ativo:** quando os canais reais existirem, tudo irá só para os destinatários de `sandbox.destinatarios`.

## Canal Teams (webhook do Workflows)

1. No Teams, num canal de teste só seu: `...` do canal, **Workflows**, modelo
   "Postar em um canal quando uma solicitação de webhook for recebida". Copie a URL gerada.
2. `python -m radar guardar-segredo teams_webhook_teste` e cole a URL (ela é um segredo).
3. `python -m radar teams-teste teste` para validar a conexão.
4. `python -m radar run demo_teams --real` para o fluxo completo com dados fictícios.

Regras do motor: dry-run nunca envia; o estado "já avisei" só é gravado **depois** de o envio dar certo
(se falhar, a próxima execução tenta de novo); sem item novo, não há mensagem; e o sandbox bloqueia
qualquer canal que não esteja em `sandbox.canais_permitidos`. A tarefa `cds_novas_do_dia` continua só com
`preview` até a TI confirmar o que pode circular no Teams.

## Sobre a consulta atual

`sql/cds_novas_do_dia.sql` devolve só as CDs do **dia mais recente** da base, de propósito (visão "novas do dia").
Por isso ela serve para avisos de novidade, mas **não** para diff de estoque nem para "parada há X dias".
Isso exigirá uma segunda consulta (estoque de CDs abertas) quando for a hora.

## Pendências com a TI

- Confirmar BitLocker no servidor (cobre temporários e previews, que a cifra por campo não cobre).
- Permissões do app registration (`Mail.Send`, `Sites.Selected`) e política de webhooks do Teams.
- Classificação da informação: o que pode circular por Teams, e-mail e SharePoint.

## Próximos passos

1. Rodar `custo` e `run cds_novas_do_dia` no servidor com a conta que vai executar o serviço.
2. Agendar no Task Scheduler (sem login interativo) e acompanhar alguns dias.
3. Canal `teams_webhook` (mesma interface do `preview`).
4. Interface web local (FastAPI em `127.0.0.1`) sobre este motor.
