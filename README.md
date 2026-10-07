# Radar Operacional

Motor de alertas e boletins operacionais. Consulta o BigQuery, descobre o que mudou e avisa as pessoas certas pelo
Teams e por e-mail. O BI responde "como está?"; o Radar responde "o que mudou e o que precisa de atenção agora?".
É um aviso auxiliar: não substitui o SAP nem o controle oficial.

A aplicação principal é o acompanhamento das **CDs abertas originadas na GFW que estão em outro centro de trabalho**
(tarefa `cds_gfw_fora_da_area`).

## Funcionalidades

| Funcionalidade | Descrição |
|---|---|
| Alerta de CD nova | Quando a tabela de origem é carregada e aparece uma CD que saiu da GFW, avisa no Teams (cartão) e por e-mail |
| Vigia sem custo | Consulta só o metadado da tabela a cada poucos minutos; a consulta pesada roda apenas quando há carga nova |
| Acompanhamento | Detecta CD **resolvida**, que **voltou para a GFW**, que **mudou de CT** ou que saiu das premissas do TURNBACK |
| Sinais de atenção | CD **parada** (sem movimento), **plano vencido**, **sem plano**, **sem responsável** |
| Gráficos no relatório diário | Uma imagem com painéis: CDs por CT atual (onde estão), por CT de origem, por tipo de defeito e por responsável |
| Indicadores de resultado | Entraram × resolvidas por semana (gráfico), saldo e tempo médio para resolver, em 7 e 30 dias |
| Vazamento por CT | De quais CTs da GFW mais saem CDs (abertas, entradas em 7/30 dias, resolvidas em 30 dias) |
| Resumo periódico | E-mail completo e cartão compacto às 7h, 12h, 14h e 18h, com o que se movimentou desde o último |
| E-mail | Visão geral, tabela de todas as CDs (nova em vermelho, atenção em amarelo) e Excel com todas as colunas |
| Saúde do robô | Avisa o dono por e-mail e o grupo no Teams em caso de falhas seguidas, e quando volta ao normal |
| Segurança | Cifragem por campo, índice cego (HMAC), segredos no Credential Manager, logs sem conteúdo, sandbox de canais |

## Como funciona o alerta (tarefa cds_gfw_fora_da_area)

1. O agendador chama `vigiar` a cada poucos minutos. O comando lê o carimbo da última carga da tabela de origem
   (metadado do BigQuery, **custo zero**).
2. Se a tabela foi carregada de novo, roda a consulta (~11,7 GB) e compara com o que já foi avisado e com a foto da
   execução anterior.
3. Para cada CD nova, monta o cartão do Teams (colunas principais) e o e-mail (estado geral + tabela + Excel).
   Para cada CD que saiu da lista ou mudou de CT, posta um cartão de movimentação.
4. Só depois de entregar com sucesso grava o estado ("já avisei", eventos, nova foto). Se falhar, a próxima verificação
   tenta de novo.
5. Sem novidade, nenhuma mensagem.

A cada execução real o robô guarda, cifrada, uma foto das CDs. Quando uma CD some da lista, ele consulta a situação atual
(`sql/resolucao_cds.sql`, poucas colunas) e classifica: *resolvida* (status I0072), *voltou para a GFW*, *saiu das
premissas do TURNBACK* (continua aberta fora da GFW, mas o filtro a excluiu) ou *não localizada*. Uma leitura **vazia**
logo após um estoque com 3 CDs ou mais só é aceita na segunda vez seguida, para não anunciar "resolvidas" por causa de
uma carga incompleta da origem.

## Sinais de atenção

Calculados em `radar/engine/sinais.py` com colunas que o SQL já devolve e configurados em `sinais:` no YAML da tarefa
(cada um liga/desliga com `ativo`). Não geram alertas próprios: aparecem no resumo, no e-mail, no cartão do Teams e na
coluna **Atenção** do Excel e da tabela (linha amarela).

| Sinal | Regra | Coluna do SQL |
|---|---|---|
| Parada | sem movimento há `limite_dias` (padrão 7) ou mais; diferente de "aberta há X dias" | `Dias_sem_Fluxo` |
| Plano vencido | data final planejada (com a hora) já passou | `Data_Plan_Final`, `Hora_Plan_Final` |
| Sem plano | sem data final planejada (datas vazias do SAP, como 0001-01-01 ou 9999-12-31, contam como ausentes) | `Data_Plan_Final` |
| Sem responsável | todos os campos de responsável vazios (ou `0`) | `Responsavel_Proxima_Acao`, `Nome_do_Responsavel_Proxima_Acao` |
| Vazamento por CT | por CT de origem na GFW: abertas, % do total, média de dias, entradas (7 e 30 dias), resolvidas (30 dias) | `Descricao_CT_Origem` |

O fuso das datas é `sinais.fuso` (America/Sao_Paulo). Se uma coluna configurada sumir do SQL, a execução falha com
`SCHEMA_MUDOU` e nada é enviado. As **entradas** por CT contam desde que o robô passou a gravar a origem de cada CD
(registros anteriores usam a origem do estoque atual).

## Resumo periódico

`python -m radar resumo <tarefa> --real`, agendado para **7h, 12h, 14h e 18h** (`scriptsgendar.ps1 ... -ResumoHoras`).
Mostra o retrato do momento, mesmo sem CD nova:

- **E-mail:** visão geral (total, mais antiga, média, por faixa, modelo e CT atual); o que se movimentou **desde o último
  resumo** (novas, resolvidas, voltaram para a GFW, mudaram de CT); pontos de atenção; vazamento por CT de origem;
  **gráficos** (painel único e entraram × resolvidas por semana); resultados (7 e 30 dias); tabela de todas as CDs
  (as novas desde o último resumo em vermelho, as que pedem atenção em amarelo) e o Excel com todas as colunas.
- **Teams:** cartão compacto com os totais, pontos de atenção, onde estão (texto) e resultados.
- O resumo só é marcado como feito depois de entregue, e o "desde o último resumo" parte dessa marca (sem ela, as últimas 24 h).

**Testar sem incomodar ninguém:** `--canais` limita o envio. O destino `email:dono` lê o segredo `email_destinatarios_dono`
(só o endereço do dono), então o resumo chega apenas na caixa do dono, não é postado no Teams e não vai para o endereço
do canal. Envio parcial não marca o resumo como feito.

```powershell
python -W ignore -m radar resumo cds_gfw_fora_da_area                                  # só prévia local
python -W ignore -m radar resumo cds_gfw_fora_da_area --real --canais email:dono --forcar-inativa   # só o e-mail do dono
```

## Gráficos do relatório diário

Só os resumos (7h, 12h, 14h e 18h) levam gráficos; alertas de CD nova e avisos técnicos não. No e-mail, uma **única imagem**
reúne os painéis configurados em `graficos:` no YAML da tarefa (hoje quatro): onde as CDs estão agora (**CT atual**),
**CT de origem** na GFW, **tipo de defeito** (a categoria do problema; o texto livre do problema não agrupa) e
**responsável pela próxima ação**. Cada painel é um ranking em barras horizontais com o valor na ponta; passando de
`top` categorias, o restante é somado em "Outros" e valores vazios aparecem como "(sem informação)". Para trocar o que
cada painel conta, basta alterar `campo` (qualquer coluna do SQL) ou incluir/remover painéis. O cartão do Teams leva só o
primeiro painel (onde estão) em texto, porque imagem não cabe no webhook.

## Indicadores de resultado

Respondem "o projeto está dando resultado?" (`radar/engine/indicadores.py`, bloco `indicadores:` do YAML, `semanas: 8`).
Aparecem no resumo por e-mail (cartões de números, gráfico de colunas por semana e tabela equivalente) e num bloco
compacto do cartão do Teams.

| Indicador | Como é calculado |
|---|---|
| Entraram | CDs avisadas pela primeira vez no período. As CDs que já estavam fora da GFW na **base de referência** (primeira execução real da tarefa) não contam |
| Resolvidas | CDs que saíram da lista como *resolvida* ou *voltou para a GFW* |
| Saldo | entraram − resolvidas; negativo significa estoque diminuindo |
| Tempo para resolver | média (e mediana) de dias em aberto da CD no momento em que saiu da lista |

Semanas de segunda a domingo (a corrente é parcial, marcada com `*`). Os números dependem do histórico acumulado: nos
primeiros dias não há dado suficiente e o gráfico não aparece. O gráfico usa duas séries de cor validadas para
daltonismo (laranja = entraram, azul = resolvidas), legenda e tabela equivalente.

## O que cada pessoa recebe

| Canal | Conteúdo | Para quem |
|---|---|---|
| Teams (canal) | Alerta de CD nova; movimentação (resolvida, voltou, mudou de CT); resumo compacto com pontos de atenção e vazamento | Equipe do canal |
| E-mail (endereço do canal + pessoas) | Visão geral, pontos de atenção com as notas, vazamento por CT, tabela completa e Excel com todas as colunas e filtro | Quem acompanha e cobra |
| E-mail só do dono | Falhas e retorno do robô, com o código do erro e o log | Dono da aplicação |

O e-mail enviado ao endereço do canal do Teams aparece dentro do canal (o anexo vai para a aba Arquivos). Cada membro do
canal só é notificado se ativar as notificações do canal. Para ver exemplos dos cartões e do e-mail sem dado
operacional: `python -m radar simular`.

## Implantação no servidor

Pré-requisitos da máquina: Windows, **Git**, **Python 3.12 ou superior** (testado com 3.14), **Google Cloud CLI**, **Outlook
clássico** com a conta logada (o e-mail usa a automação do Outlook; o "Novo Outlook" não a possui), acesso ao BigQuery e
ao Teams, e um usuário que **permaneça com a sessão aberta** (as tarefas agendadas rodam como esse usuário; desconectar o
RDP é aceitável, sair/fazer logoff não). Desativar suspensão e hibernação da máquina.

### 1. Clonar e instalar

```powershell
New-Item -ItemType Directory -Force C:\Repositorios | Out-Null; cd C:\Repositorios
git clone https://github.com/Pedrocs50/radar-operacional.git "Radar Operacional"
cd "Radar Operacional"
python -m venv .venv                      # se "python" não for reconhecido, use: py -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

**Não é preciso "ativar" o ambiente.** Em muitos servidores o PowerShell bloqueia `.venv\Scripts\activate` ("a execução de
scripts foi desabilitada neste sistema"). Todos os comandos deste README funcionam trocando `python` por
`.venv\Scripts\python` (por exemplo, `.venv\Scripts\python -m radar doctor`). Se preferir ativar, liberar uma vez com
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`. Os scripts agendados já usam o Python do `.venv` e ignoram essa política.

O repositório contém o ID do projeto do BigQuery, o nome da tabela e os códigos das CTs: manter **privado**.

**O que o clone não traz (de propósito) e precisa ser configurado no servidor:**

| Item | Onde |
|---|---|
| `.venv/` | passo 1 |
| Login do BigQuery | passo 2 |
| Chaves de cifragem | passo 3 |
| Segredos (URL do webhook do Teams, e-mails) | passo 4 |
| `data/` (banco, prévias, logs) | criada na primeira execução |
| Tarefas agendadas | passo 6 |

### 2. Login do BigQuery

```powershell
gcloud auth application-default login      # com a conta que vai rodar o robô
```

Se `gcloud` não for reconhecido, abrir um terminal novo ou incluir `%LOCALAPPDATA%\Google\Cloud SDK\google-cloud-sdk\bin`
no PATH. Conferir `bigquery.job_project` em `config\settings.yaml`.

### 3. Chaves de cifragem

As chaves ficam no Credential Manager do Windows (serviço `radar-operacional`, itens `enc_keys` e `hmac_key`) e não estão
no repositório. **Faça backup das chaves separado do banco: sem elas o histórico é irrecuperável.**

- **Instalação nova:** `python -m radar init-keys`.
- **Migração de outra máquina** (mantém histórico, "já avisei" e eventos): exportar os valores na máquina antiga,
  restaurar no servidor e copiar `data\radar.db` (com o robô parado, junto de `radar.db-wal` e `-shm` se existirem):

```powershell
# máquina antiga: mostra os valores (guardar em local seguro; nunca em chat, e-mail ou git)
python -c "import keyring; print(keyring.get_password('radar-operacional','enc_keys')); print(keyring.get_password('radar-operacional','hmac_key'))"
# servidor: restaurar
python -c "import keyring; keyring.set_password('radar-operacional','enc_keys','<ENC>'); keyring.set_password('radar-operacional','hmac_key','<HMAC>')"
```

### 4. Segredos de canal

Copiar o valor com Ctrl+C e rodar, um de cada vez (o valor não aparece na tela):

```powershell
python -W ignore -m radar guardar-segredo teams_webhook_teste --da-area-de-transferencia        # URL do fluxo do Teams
python -W ignore -m radar guardar-segredo email_destinatarios_teste --da-area-de-transferencia  # "endereco-do-canal@amer.teams.ms; pessoa@empresa.com.br"
python -W ignore -m radar guardar-segredo email_destinatarios_dono --da-area-de-transferencia   # só o dono: avisos técnicos
```

- **Fluxo do Teams:** no canal, `...` → **Workflows** → modelo "Send webhook alerts to a channel"; copiar a URL gerada.
  O fluxo fica ligado à conta de quem o criou (convém ter um co-proprietário). Se a URL for de um fluxo apagado ou de
  outro canal, o teste devolve `TEAMS_HTTP_404` ou `401`: recriar o fluxo e guardar a URL nova.
- **Endereço do canal:** no canal, `...` → **Obter endereço de e-mail**.
- Os destinos usam o nome após os dois pontos: o canal `teams:teste` lê o segredo `teams_webhook_teste`; `email:teste`
  lê `email_destinatarios_teste`; `email:dono` lê `email_destinatarios_dono`.

### 5. Validar e criar a base de referência

```powershell
python -W ignore -m radar doctor cds_gfw_fora_da_area                           # confere o ambiente (não envia nada)
python -m pytest -q                                                             # testes
python -W ignore -m radar custo cds_gfw_fora_da_area                            # ~11,7 GB
python -W ignore -m radar teams-teste teste                                     # mensagem de teste chega no canal
python -W ignore -m radar simular --enviar                                      # cartões de EXEMPLO no canal de teste
python -W ignore -m radar run cds_gfw_fora_da_area                              # dry-run: prévias em data\preview_tmp
python -W ignore -m radar resumo cds_gfw_fora_da_area --real --canais email:dono --forcar-inativa  # e-mail completo só ao dono
python -W ignore -m radar base-referencia cds_gfw_fora_da_area                  # registra o estoque atual como já conhecido (não envia nada)
```

- `doctor` deve terminar em "Ambiente em ordem"; qualquer `[FALTA]` aponta o que falta (chave, segredo, login do BigQuery,
  Outlook).
- **`base-referencia` precisa rodar antes de qualquer `vigiar` real.** Sem ela, as CDs que já estão fora da GFW seriam
  tratadas como novas e **todas** seriam alertadas no Teams e por e-mail de uma vez. Ela grava o estoque atual como conhecido,
  sem enviar nada; só as CDs que aparecerem depois disparam alerta. Os indicadores também usam essa execução como ponto de
  partida (o que já existia não conta como "entrada"). Em migração com o banco copiado (passo 3), ela não é necessária.
- Para o e-mail, `email.modo: rascunho` no `tasks\cds_gfw_fora_da_area.yaml` abre a mensagem no Outlook sem enviar (voltar para
  `enviar` depois). O Outlook pode exibir um aviso de segurança na primeira automação.
- A tarefa vem com `ativa: false` por segurança; os scripts de agendamento já passam `--forcar-inativa`, então não é
  obrigatório mudar. Para não depender do parâmetro, defina `ativa: true` no YAML.

### 6. Agendar

Com o usuário que roda o robô (ele precisa estar conectado: o login do gcloud, o Credential Manager e o Outlook são dele):

```powershell
powershell -File scripts\agendar.ps1 cds_gfw_fora_da_area -VigiarACadaMin 5
powershell -File scripts\agendar.ps1 cds_gfw_fora_da_area -ResumoHoras 07:00,12:00,14:00,18:00
```

Cria `Radar-vigia-cds_gfw_fora_da_area` e `Radar-resumo-cds_gfw_fora_da_area` no Agendador de Tarefas. Conferir lá a conta,
"Executar somente quando o usuário estiver conectado" e que a máquina não hiberna. Testar com "Executar" e ver os logs em
`data\logs` (`vigia-*.log`, `resumo-*.log`).

### 7. Operar

```powershell
python -W ignore -m radar status cds_gfw_fora_da_area         # OK / ALERTA (última execução real)
python -W ignore -m radar historico                           # execuções e GB lidos por execução
python -W ignore -m radar atualizacoes cds_gfw_fora_da_area   # cadência real das cargas (define o custo)
python -W ignore -m radar doctor cds_gfw_fora_da_area         # diagnóstico do ambiente
Get-ScheduledTask | Where-Object TaskName -like 'Radar*'     # o que está agendado nesta máquina
```

**Desligar ou descomissionar uma máquina:**

```powershell
Unregister-ScheduledTask -TaskName "Radar-vigia-cds_gfw_fora_da_area" -Confirm:$false
Unregister-ScheduledTask -TaskName "Radar-resumo-cds_gfw_fora_da_area" -Confirm:$false
python -m radar limpar                                         # apaga prévias, imagens e Excel antigos
```

Para remover os dados de uma máquina: apagar `data\` (banco, prévias, logs) e os itens `radar-operacional` e os segredos no
Gerenciador de Credenciais do Windows.

### Configuração

| Onde | O que ajustar |
|---|---|
| `config\settings.yaml` | `bigquery.job_project` (projeto onde os jobs rodam), `bigquery.max_bytes_billed` (teto por consulta), `storage.db_path`, `preview.retencao_horas`, `retencao.mensagens_dias`, `email.dominios_permitidos`, `sandbox` |
| `tasks\cds_gfw_fora_da_area.yaml` | `canais` (destinos), `email.modo` e `email.remetente`, `sinais` (limites), `graficos` (painéis), `indicadores`, `saude`, `acompanhamento`, `mensagem` (colunas e rótulos) |

**Sandbox:** enquanto `sandbox.ativo: true`, só os canais listados em `sandbox.canais_permitidos` recebem envio real, e os
cartões e e-mails levam o aviso "SANDBOX: mensagem de teste". Para um canal novo (por exemplo `teams:gfw`): criar o fluxo no
canal, guardar o segredo `teams_webhook_gfw`, incluir `"teams:gfw"` em `canais` da tarefa e em `sandbox.canais_permitidos`.
Quando a TI liberar o uso em produção, definir `sandbox.ativo: false` remove o aviso e libera os canais da tarefa.

### Atualizar a versão no servidor

```powershell
cd "C:\Repositorios\Radar Operacional"
git pull
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -W ignore -m radar doctor cds_gfw_fora_da_area
```

Não é preciso reiniciar nada: cada chamada agendada carrega o código atual. Os segredos, as chaves e `data\` ficam como estão.

### Adicionar ou remover pessoas

**Antes de incluir qualquer pessoa**, confirmar com a TI e a segurança da informação o que pode circular por Teams e e-mail:
os alertas e o Excel levam dado operacional de aviação. Quem recebe pode ser configurado de dois jeitos, que se somam.

**1. Pelo Teams (canal).** Adicionar a pessoa como membro da equipe ou do canal (no Teams: `...` da equipe -> **Adicionar
membro**). Ela passa a ver os cartões e os e-mails que chegam ao canal. Para ser notificada, cada membro ativa as notificações
do canal (`...` do canal -> **Notificações do canal** -> **Todas as atividades**). Nada muda no Radar.

**2. Na caixa de entrada (e-mail).** O destino `email:teste` lê a lista do segredo `email_destinatarios_teste` (hoje: o endereço
do canal do Teams e o e-mail do dono). Use o comando `destinatarios`, que **não apaga os que já estão na lista**
(`guardar-segredo` substitui a lista inteira):

```powershell
python -W ignore -m radar destinatarios teste                                              # mostra quem recebe hoje
python -W ignore -m radar destinatarios teste --adicionar maria@empresa.com.br joao@empresa.com.br
python -W ignore -m radar destinatarios teste --remover joao@empresa.com.br
```

- A mudança vale na **próxima mensagem**: não é preciso reiniciar nem reagendar.
- Quem está na lista recebe o **alerta de CD nova** e os **resumos** (7h, 12h, 14h e 18h), com tabela, gráficos e Excel.
- **Só domínios corporativos:** `email.dominios_permitidos` em `config\settings.yaml` (hoje `embraer.com.br` e
  `amer.teams.ms`, o domínio do endereço de e-mail dos canais). O comando recusa outros domínios, e o envio também; para
  liberar um domínio, edite essa lista de propósito. Sem a chave, não há restrição.
- Para mandar uma mensagem de verificação a **todos** da lista: `python -W ignore -m radar resumo cds_gfw_fora_da_area --real
  --canais email:teste --forcar-inativa`. Para testar só com o dono: `--canais email:dono`.
- O e-mail sai **em nome de quem está logado no Outlook** do servidor, e os destinatários verão esse remetente. Para sair em
  nome de uma caixa compartilhada, definir `email.remetente` no YAML da tarefa (exige a permissão "Enviar como").
- Enquanto `sandbox.ativo: true`, assunto e corpo levam "TESTE" / "SANDBOX". Quando a TI liberar o uso, definir
  `sandbox.ativo: false` em `config\settings.yaml`.

**Grupos diferentes** (por exemplo uma coordenação que receba por e-mail separado): criar outro destino, por exemplo
`email:coordenacao` -> `python -m radar destinatarios coordenacao --adicionar ...`, incluir `"email:coordenacao"` em `canais` da
tarefa e em `sandbox.canais_permitidos`. Cada destino recebe tudo o que a tarefa envia por e-mail; separar por tipo de
mensagem ou por área ainda não é suportado (próximo passo: segmentar por `Descricao_Area_Responsavel`).

**Quem não pode receber:** o robô nunca envia para domínio fora da lista permitida, e o Excel anexo tem todas as colunas
do SQL; trate-o como dado operacional.

## Comandos

| Comando | O que faz |
|---|---|
| `python -m radar listar` | Lista as tarefas |
| `python -m radar custo <tarefa>` | Estima os bytes lidos (dry_run do BigQuery) |
| `python -m radar run <tarefa>` | Dry-run: gera prévia, imagens e e-mail de prévia; **não** grava estado nem envia |
| `python -m radar run <tarefa> --real --forcar-inativa` | Entrega aos canais permitidos e grava o estado "já avisei" |
| `python -m radar run <tarefa> --todos --limite 1` | Ignora o "já avisei" e usa só N itens (teste de envio) |
| `python -m radar destinatarios <destino> [--adicionar ...] [--remover ...]` | Mostra, adiciona ou remove e-mails de um destino (ex.: `teste`) sem apagar os demais |
| `python -m radar base-referencia <tarefa>` | Registra o estoque atual como já conhecido **sem enviar nada** (rodar antes do primeiro `vigiar` real) |
| `python -m radar vigiar <tarefa> --forcar-inativa` | Verifica (de graça) se a origem mudou; se sim, roda e avisa |
| `python -m radar resumo <tarefa> [--real] [--canais ...]` | Resumo do estoque: prévia (padrão) ou envio; `--canais email:dono` envia só ao e-mail do dono |
| `python -m radar simular [--enviar]` | Cartões e e-mail de **exemplo** (JSON, visualizador `cartoes.html`); `--enviar` posta no canal de teste |
| `python -m radar doctor [tarefa]` | Confere chaves, segredos, banco, BigQuery, Outlook, agendamentos e sandbox |
| `python -m radar atualizacoes <tarefa>` | Cargas da origem detectadas (cadência) |
| `python -m radar status <tarefa>` | Heartbeat: código de saída 1 se a última execução real falhou ou está antiga |
| `python -m radar init-keys` | Gera as chaves de cifragem e de HMAC |
| `python -m radar guardar-segredo <nome> [--da-area-de-transferencia]` | Guarda um segredo no Credential Manager |
| `python -m radar teams-teste teste` | Mensagem de teste (sem dado operacional) ao canal |
| `python -m radar historico` / `limpar` | Últimas execuções (com GB lidos) / aplica retenção |
| `python -m pytest` | Roda os testes |

Scripts (PowerShell) em `scripts\`: `rodar.ps1` (execução real com log), `vigiar.ps1` (verificação do vigia), `resumo.ps1`,
`agendar.ps1` (cria as tarefas agendadas) e `enviar_email.ps1` (usado pelo canal de e-mail; não é para uso manual).

## Custo do BigQuery

Perguntar "a tabela mudou?" lê só o metadado (custo zero). A consulta de ~11,7 GB só roda quando a tabela é carregada de
novo, então o custo é (cargas por dia) x 11,7 GB; resultado em cache no mesmo dia pode custar 0. `radar historico` mostra
os GB de cada execução, `radar atualizacoes` mostra a cadência real das cargas, e `bigquery.max_bytes_billed`
(`config\settings.yaml`) é o teto por consulta: se passar disso a consulta falha em vez de custar mais.

## Saúde do robô

Cada chamada do vigia é registrada. Com `saude.limiar_falhas` falhas seguidas (3 x 5 min), o dono recebe e-mail com o
código do erro e as últimas linhas do log (sem dado operacional) e o grupo recebe um cartão simples no Teams ("problema
técnico, já sendo verificado"). Ao voltar, os dois recebem o aviso de recuperação. Se ficar mais de `saude.lacuna_min`
minutos sem verificação (máquina desligada, reinício), só o dono é avisado quando o robô volta. Um robô desligado não
consegue avisar que está desligado: isso exige um monitor externo.

## Estrutura

```
radar/
  storage/   crypto.py (Fernet + índice cego) e db.py (único lugar com SQL)
  sources/   bigquery.py (consulta, custo, carimbo de atualização, resolução de notas), demo.py
  channels/  teams_webhook.py, email_outlook.py, email_conteudo.py, imagem.py, imagem_tabela.py, grafico.py, preview.py
  engine/    runner.py (fonte -> novos -> mensagem -> canais -> estado -> log), movimentos.py, sinais.py,
             indicadores.py, paineis.py, resumo.py
  saude.py   avisos de falha e recuperação      doctor.py  diagnóstico do ambiente
  simulacao.py  exemplos de cartões e e-mail    templates/  preview.html.j2, email.html.j2
config/      settings.yaml (projeto do BigQuery, teto de custo, retenção, sandbox)
sql/         cds_gfw_fora_da_area.sql, cds_novas_do_dia.sql (consultas originais, sem alterações), resolucao_cds.sql
tasks/       uma tarefa por YAML (fonte, mensagem, canais, acompanhamento, sinais, resumo, saúde, e-mail)
scripts/     rodar.ps1, vigiar.ps1, resumo.ps1, agendar.ps1, enviar_email.ps1
tests/       pytest, com dados fictícios
data/        SQLite, prévias, imagens e logs (fora do git)
docs/        documentação técnica do projeto (PDF): funcionamento, decisões, estado atual e guia para retomar o trabalho
```

## Decisões de projeto

- **Tudo é uma tarefa** (YAML): fonte, modo, mensagem, canais e demais blocos. Nova tarefa = novo YAML (e novo SQL).
- **Dry-run por padrão.** Só `--real` (ou o vigia) grava o estado "já avisei".
- **Anti-repetição:** a chave do item (`Nota_QM`) vira um HMAC-SHA256 (índice cego); o banco compara hashes e nunca vê o valor.
- **Cifrado no banco:** mensagens, itens, fotos e eventos. **Em claro:** ids internos, datas, status, contagens, código de erro.
- **Logs:** só códigos e tipos de erro, nunca conteúdo. A URL do webhook nunca aparece em log ou erro (`TEAMS_URL_INVALIDA`).
- **Prévias, imagens e Excel** contêm dado operacional em claro: pasta temporária com retenção de 24 h (`radar limpar`).
  A cifra por campo não cobre esses arquivos; usar disco cifrado (BitLocker) no servidor.
- **Sandbox:** só os canais de `sandbox.canais_permitidos` recebem envio real. Se o sandbox bloquear todos os canais externos
  de uma tarefa, o estado "já avisei" não é gravado, para o item ser entregue quando o canal for liberado.
- **Entrega antes do estado:** nada é marcado como avisado antes de a entrega dar certo.
- **Consultas originais intocadas:** o SQL é executado exatamente como foi escrito; ajustes ficam no Python.

## Limitações conhecidas

- **E-mail pelo Outlook clássico:** exige o Outlook instalado e um usuário logado, e o e-mail sai em nome desse usuário.
  A versão sem essa dependência usa Microsoft Graph (`Mail.Send`) trocando só `channels/email_outlook.py`; para sair em nome
  de uma caixa compartilhada, `email.remetente` (permissão "Enviar como").
- O aviso nunca é mais atualizado que a carga do SAP para o BigQuery (a mensagem mostra "dados de HH:MM").
- Se uma tarefa tiver dois canais externos e só o segundo falhar, o primeiro é reenviado na nova tentativa. Se o processo cair
  entre entregar e gravar o estado, o alerta pode ser reenviado uma vez.
- Imagens não cabem no webhook do Teams (~28 KB por cartão); elas vão por e-mail.
- O remetente no Teams é o app "Workflows" da Microsoft; nome e foto próprios exigem um bot registrado.
- No Teams, os membros só são notificados se ativarem as notificações do canal (ou com @menção, ainda não implementada).

## Pendências e próximos passos

- Classificação da informação com a TI: o que pode circular por Teams, e-mail e SharePoint (antes de incluir mais pessoas).
- Conta de serviço para o BigQuery, caixa compartilhada para o e-mail e co-proprietário do fluxo do Teams.
- Permissões do app registration (`Mail.Send`, `Sites.Selected`) para e-mail e SharePoint sem depender do Outlook.
- Segmentar por `Descricao_Area_Responsavel` (cada coordenação recebe só as suas CDs).
- Pasta do SharePoint com as imagens e o Excel, e link no cartão do Teams.
- @menção das pessoas no cartão; reaviso por idade; interface web local e perfis por pessoa.
