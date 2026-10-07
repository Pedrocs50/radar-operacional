"""CLI: python -m radar <comando>"""
from __future__ import annotations

import argparse
import sys
from getpass import getpass

from . import config, segredos
from .channels import email_outlook, preview, teams_webhook
from .channels.base import ErroDeEnvio
from . import saude
from .engine.resumo import executar_resumo
from .engine.runner import executar
from .storage import crypto as cr
from .storage.db import Storage


def _abrir(settings):
    c = cr.carregar_crypto()
    return c, Storage(config.RAIZ / settings["storage"]["db_path"], c)


def cmd_init_keys(args):
    enc, hm = cr.gerar_chaves()
    if args.env:
        print(f"{cr.ENV_ENC}={enc}\n{cr.ENV_HMAC}={hm}")
        print("\nGuarde estes valores em local seguro (backup separado do banco).", file=sys.stderr)
        return
    cr.salvar_no_keyring(enc, hm)
    print("Chaves gravadas no gerenciador de credenciais do sistema (keyring).")
    print("Faça backup das chaves separado do banco: sem elas o histórico é irrecuperável.")


def _ler_area_de_transferencia() -> str:
    import subprocess

    r = subprocess.run(["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"],
                       capture_output=True, text=True, encoding="utf-8")
    return r.stdout.strip()


def cmd_guardar_segredo(args):
    if args.da_area_de_transferencia:
        valor = _ler_area_de_transferencia()
    else:
        valor = getpass(f"Valor do segredo '{args.nome}' (não aparece na tela): ").strip()
    if not valor:
        print("Valor vazio, nada foi guardado.")
        return 2
    if args.nome.startswith("email_destinatarios_"):
        try:
            email_outlook.parse_destinatarios(valor)
        except ErroDeEnvio:
            print("Isto não parece uma lista de e-mails (separe por ponto e vírgula). Nada foi guardado.")
            return 2
    if args.nome.startswith("teams_webhook_") and not teams_webhook.url_bem_formada(valor):
        print("Isto não parece uma única URL (veio com espaços, caracteres estranhos ou colada duas vezes). "
              "Nada foi guardado. Dica: copie a URL de novo e use --da-area-de-transferencia.")
        return 2
    segredos.salvar(args.nome, valor)
    print("Guardado no gerenciador de credenciais.")


def cmd_teams_teste(args):
    try:
        url = segredos.obter(f"teams_webhook_{args.destino}")
        teams_webhook.enviar(teams_webhook.mensagem_de_teste(), url)
    except RuntimeError as e:
        print(e)
        return 1
    except ErroDeEnvio as e:
        print(f"Falhou: {e.codigo}")
        return 1
    print("Enviado. Confira o canal no Teams.")


def cmd_listar(args):
    for t in config.listar_tarefas():
        print(f"{t['id']:<24} ativa={t.get('ativa', False)!s:<5} canais={','.join(t['canais'])}  {t['nome']}")


def cmd_run(args):
    settings = config.carregar_settings()
    task = config.carregar_tarefa(args.task)
    c, st = _abrir(settings)
    real = args.real
    if real and not task.get("ativa", False) and not args.forcar_inativa:
        print("Tarefa está com ativa: false. Use --forcar-inativa para registrar mesmo assim.")
        return 2
    try:
        res = executar(task, config.montar_fonte(task, settings), st, c, settings,
                       dry_run=not real, forcar_todos=args.todos, limite=args.limite)
    except ErroDeEnvio as e:
        print(f"Falha no envio: {e.codigo}. Nada foi marcado como avisado; a próxima execução tenta de novo.")
        return 1
    modo = "REAL" if real else "DRY-RUN"
    print(f"[{modo}] execução {res['execucao_id']}: {res['status']} | itens={res['n_itens']} novos={res['n_novos']}")
    print(f"Prévia: {res['preview']}")
    if res.get("email_previa"):
        print(f"Prévia do e-mail: {res['email_previa']}")
    if res["enviados"]:
        print("Enviado para: " + ", ".join(res["enviados"]))
    if res["bloqueados_sandbox"]:
        print("Bloqueado pelo sandbox (não está em canais_permitidos): " + ", ".join(res["bloqueados_sandbox"]))
    if not real and any(c != "preview" for c in task.get("canais", [])):
        print("Dry-run: nada foi enviado para os canais externos.")


def cmd_custo(args):
    settings = config.carregar_settings()
    task = config.carregar_tarefa(args.task)
    fonte = config.montar_fonte(task, settings)
    if not hasattr(fonte, "estimar_custo"):
        print("Esta fonte não tem estimativa de custo.")
        return
    info = fonte.estimar_custo()
    print(f"Bytes que a consulta leria: {info['bytes_processados']:,}")


def cmd_historico(args):
    settings = config.carregar_settings()
    _, st = _abrir(settings)
    for e in st.listar_execucoes(args.task, args.limite):
        print(f"#{e['id']:<4} {e['inicio']}  {e['task_id']:<20} {e['status']:<13} "
              f"dry={e['dry_run']} itens={e['n_itens']} novos={e['n_novos']} "
              f"GB={(e['bytes_processados'] or 0) / 1e9:.1f} erro={e['codigo_erro'] or '-'}")


def cmd_limpar(args):
    settings = config.carregar_settings()
    _, st = _abrir(settings)
    msgs = st.limpar_mensagens_antigas(args.dias or settings["retencao"]["mensagens_dias"])
    pasta = config.RAIZ / settings["preview"]["dir"]
    htmls = preview.limpar_antigos(pasta, settings["preview"]["retencao_horas"])
    tecnicos = st.limpar_historico_tecnico(14)
    print(f"Mensagens antigas apagadas: {msgs} | previews apagados: {htmls} | registros técnicos: {tecnicos}")


def cmd_vigiar(args):
    """Pergunta (de graça) se a tabela de origem foi atualizada; só então roda a consulta e avisa.

    Feito para ser chamado a cada poucos minutos pelo agendador. Cada atualização da origem é
    tratada uma vez; se a execução falhar, a atualização não é marcada e a próxima chamada tenta de novo.
    Cada chamada alimenta a saúde do robô: falhas seguidas e retorno avisam o dono e o grupo.
    """
    settings = config.carregar_settings()
    task = config.carregar_tarefa(args.task)
    if not task.get("ativa", False) and not args.forcar_inativa:
        print("Tarefa está com ativa: false. Use --forcar-inativa para vigiar mesmo assim.")
        return 2
    c, st = _abrir(settings)
    ok, codigo = True, None
    try:
        fonte = config.montar_fonte(task, settings)
        if not hasattr(fonte, "ultima_atualizacao"):
            print("Esta fonte não informa a data de atualização.")
            return 2
        modificada = fonte.ultima_atualizacao()
        if st.atualizacao_ja_tratada(task["id"], modificada) and not args.forcar:
            print(f"Sem atualização na origem (última carga: {modificada}).")
        else:
            res = executar(task, fonte, st, c, settings, dry_run=False)
            st.registrar_atualizacao(task["id"], modificada)
            print(f"Origem atualizada em {modificada}: execução {res['execucao_id']} | "
                  f"itens={res['n_itens']} novos={res['n_novos']} movimentos={res['n_movimentos']}")
            if res["enviados"]:
                print("Enviado para: " + ", ".join(res["enviados"]))
    except ErroDeEnvio as e:
        ok, codigo = False, e.codigo
        print(f"Falha: {codigo}. Será tentado de novo na próxima verificação.")
    except Exception as e:  # só o tipo: a mensagem pode citar dados
        ok, codigo = False, type(e).__name__
        print(f"Falha: {codigo}. Será tentado de novo na próxima verificação.")
    aviso = saude.processar(st, task["id"], ok, codigo, saude.montar_avisador(settings, task), task.get("saude"))
    if aviso:
        print(f"Aviso de saúde disparado: {aviso}")
    return 0 if ok else 1


def cmd_destinatarios(args):
    """Mostra, adiciona ou remove destinatários de um destino de e-mail (segredo email_destinatarios_<destino>).

    Existe para não ter de reescrever a lista inteira (guardar-segredo substitui tudo)."""
    settings = config.carregar_settings()
    dominios = settings.get("email", {}).get("dominios_permitidos")
    nome = f"email_destinatarios_{args.destino}"
    try:
        atual = email_outlook.parse_destinatarios(segredos.obter(nome))
    except RuntimeError:
        atual = []
    adicionar = [e.strip().lower().strip(";,") for e in (args.adicionar or [])]
    remover = {e.strip().lower().strip(";,") for e in (args.remover or [])}
    for e in adicionar:
        if "@" not in e or " " in e:
            print(f"'{e}' não parece um e-mail. Nada foi alterado.")
            return 2
        if not email_outlook.dominio_permitido(e, dominios):
            print(f"'{e}' não está em um domínio permitido ({', '.join(dominios)}). Dado operacional só vai para contas "
                  "corporativas. Nada foi alterado.")
            return 2
    if adicionar or remover:
        final: list[str] = []
        for e in atual + adicionar:
            if e.lower() not in remover and e.lower() not in {x.lower() for x in final}:
                final.append(e)
        faltou = remover - {e.lower() for e in atual}
        if faltou:
            print("Não estavam na lista: " + ", ".join(sorted(faltou)))
        if not final:
            print("A lista ficaria vazia. Nada foi alterado.")
            return 2
        segredos.salvar(nome, "; ".join(final))
        atual = final
        print("Lista atualizada.")
    print(f"Destinatários de email:{args.destino} ({len(atual)}):")
    for e in atual:
        print("  - " + e)
    if not atual:
        print("  (nenhum; use --adicionar)")


def cmd_base_referencia(args):
    """Registra o estoque atual como "já conhecido" SEM enviar nada (primeira execução em uma máquina nova).

    Sem isso, o primeiro `vigiar` trataria todas as CDs que já estão fora da GFW como novas e alertaria todas."""
    settings = config.carregar_settings()
    task = config.carregar_tarefa(args.task)
    c, st = _abrir(settings)
    conhecidas = len(st.hashes_ja_avisados(task["id"]))
    fonte = config.montar_fonte(task, settings)
    res = executar({**task, "canais": ["preview"]}, fonte, st, c, settings, dry_run=False)  # só prévia local: nada é enviado
    if hasattr(fonte, "ultima_atualizacao"):
        st.registrar_atualizacao(task["id"], fonte.ultima_atualizacao())
    print(f"Base de referência gravada: {res['n_itens']} CD(s) lidas, {res['n_novos']} registradas agora "
          f"({conhecidas} já eram conhecidas). Nada foi enviado.")


def cmd_resumo(args):
    """Resumo periódico do estoque (ver radar/engine/resumo.py). Dry-run por padrão."""
    settings = config.carregar_settings()
    task = config.carregar_tarefa(args.task)
    if args.real and not task.get("ativa", False) and not args.forcar_inativa:
        print("Tarefa está com ativa: false. Use --forcar-inativa para enviar mesmo assim.")
        return 2
    c, st = _abrir(settings)
    try:
        canais = [x.strip() for x in args.canais.split(",")] if args.canais else None
        res = executar_resumo(task, config.montar_fonte(task, settings), st, c, settings, dry_run=not args.real,
                              canais=canais)
    except ErroDeEnvio as e:
        print(f"Falha no envio: {e.codigo}. O resumo não foi marcado como feito.")
        return 1
    p = res["periodo"]
    print(f"[{'REAL' if args.real else 'DRY-RUN'}] resumo {res['execucao_id']}: abertas={res['n_itens']} "
          f"novas={p['novas']} resolvidas={p['resolvida'] + p['voltou_gfw']} mudaram_ct={p['mudou_ct']}")
    print(f"Prévia do e-mail: {res['previa']}")
    if res["enviados"]:
        print("Enviado para: " + ", ".join(res["enviados"]))
    if res["bloqueados_sandbox"]:
        print("Bloqueado pelo sandbox: " + ", ".join(res["bloqueados_sandbox"]))


def cmd_simular(args):
    """Mostra como ficam os cartões e o e-mail com dados de EXEMPLO (marcados como tal). Nada operacional é usado.

    Sem --enviar: grava os cartões em data/preview_tmp/simulacao (JSON do Adaptive Card, que pode ser colado em
    https://adaptivecards.io/designer) e o e-mail de exemplo. Com --enviar: posta os cartões no canal de teste."""
    from . import simulacao

    settings = config.carregar_settings()
    task = config.carregar_tarefa(args.task)
    pasta = config.RAIZ / settings["preview"]["dir"] / "simulacao"
    exemplos = simulacao.exemplos(task, settings)
    arquivos = simulacao.salvar(exemplos, pasta, task)
    for nome, caminho in arquivos.items():
        print(f"{nome}: {caminho}")
    if not args.enviar:
        print("\nNada foi enviado. Use --enviar para postar os cartões no canal de teste.")
        return 0
    canal = args.canal
    sandbox = settings.get("sandbox", {})
    if sandbox.get("ativo", True) and canal not in sandbox.get("canais_permitidos", []):
        print(f"Canal {canal} não está em sandbox.canais_permitidos.")
        return 2
    try:
        url = segredos.obter("teams_webhook_" + canal.split(":", 1)[1])
        for nome, msg in exemplos.items():
            teams_webhook.enviar(msg, url)
            print(f"Enviado: {nome}")
    except (RuntimeError, ErroDeEnvio) as e:
        print(f"Falhou: {getattr(e, 'codigo', 'SEGREDO_AUSENTE')}")
        return 1


def cmd_doctor(args):
    """Confere chaves, segredos, banco, BigQuery, Outlook, tarefas agendadas e sandbox (sem enviar nada)."""
    from . import doctor

    settings = config.carregar_settings()
    task = config.carregar_tarefa(args.task) if args.task else None
    problemas = 0
    for nome, ok, detalhe in doctor.verificar(settings, task):
        print(f"[{'OK' if ok else 'FALTA'}] {nome}: {detalhe}")
        problemas += 0 if ok else 1
    print(f"\n{problemas} item(ns) para resolver." if problemas else "\nAmbiente em ordem.")
    return 1 if problemas else 0


def cmd_atualizacoes(args):
    """Mostra quando a origem mudou (para descobrir a cadência de carga)."""
    settings = config.carregar_settings()
    _, st = _abrir(settings)
    for a in st.listar_atualizacoes(args.task, args.limite):
        print(f"carga da origem: {a['modificada_em']}   detectada: {a['detectada_em']}")


def cmd_status(args):
    """Heartbeat: sai com código 1 se a última execução real da tarefa for antiga demais ou falhou."""
    from datetime import datetime, timezone

    settings = config.carregar_settings()
    _, st = _abrir(settings)
    reais = [e for e in st.listar_execucoes(args.task, 50) if not e["dry_run"] and e["status"] != "rodando"]
    if not reais:
        print(f"ALERTA: nenhuma execução real registrada para '{args.task}'.")
        return 1
    ultima = reais[0]
    idade = (datetime.now(timezone.utc) - datetime.fromisoformat(ultima["inicio"])).total_seconds() / 3600
    print(f"Última execução real: #{ultima['id']} há {idade:.1f} h, status={ultima['status']}, erro={ultima['codigo_erro'] or '-'}")
    if ultima["status"] == "falha":
        print("ALERTA: a última execução falhou.")
        return 1
    if idade > args.max_horas:
        print(f"ALERTA: sem execução há mais de {args.max_horas} h.")
        return 1
    print("OK")


def main(argv=None):
    p = argparse.ArgumentParser(prog="radar")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init-keys", help="gera e guarda as chaves de cifragem")
    s.add_argument("--env", action="store_true", help="só imprime (uso em desenvolvimento)")
    s.set_defaults(fn=cmd_init_keys)

    s = sub.add_parser("guardar-segredo", help="guarda um segredo (ex.: URL do webhook) no Credential Manager")
    s.add_argument("nome", help="ex.: teams_webhook_teste")
    s.add_argument("--da-area-de-transferencia", action="store_true",
                   help="lê o valor copiado (Ctrl+C) em vez de pedir para colar; evita erro de colagem")
    s.set_defaults(fn=cmd_guardar_segredo)

    s = sub.add_parser("teams-teste", help="envia uma mensagem de teste (sem dados operacionais)")
    s.add_argument("destino", help="ex.: teste (usa o segredo teams_webhook_teste)")
    s.set_defaults(fn=cmd_teams_teste)

    s = sub.add_parser("listar", help="lista as tarefas")
    s.set_defaults(fn=cmd_listar)

    s = sub.add_parser("run", help="executa uma tarefa (dry-run por padrão)")
    s.add_argument("task")
    s.add_argument("--real", action="store_true", help="envia aos canais e registra snapshot e estado de alertas")
    s.add_argument("--todos", action="store_true", help="mostra todos os itens, não só os novos")
    s.add_argument("--forcar-inativa", action="store_true")
    s.add_argument("--limite", type=int, help="usa só os N primeiros itens (para testar o envio)")
    s.set_defaults(fn=cmd_run)

    s = sub.add_parser("custo", help="estima bytes lidos no BigQuery (dry_run)")
    s.add_argument("task")
    s.set_defaults(fn=cmd_custo)

    s = sub.add_parser("historico", help="últimas execuções")
    s.add_argument("--task")
    s.add_argument("--limite", type=int, default=20)
    s.set_defaults(fn=cmd_historico)

    s = sub.add_parser("limpar", help="aplica retenção (mensagens e previews)")
    s.add_argument("--dias", type=int)
    s.set_defaults(fn=cmd_limpar)

    s = sub.add_parser("vigiar", help="verifica se a origem mudou; se sim, roda e avisa (para o agendador)")
    s.add_argument("task")
    s.add_argument("--forcar", action="store_true", help="roda mesmo sem atualização nova")
    s.add_argument("--forcar-inativa", action="store_true")
    s.set_defaults(fn=cmd_vigiar)

    s = sub.add_parser("destinatarios", help="mostra, adiciona ou remove e-mails de um destino (ex.: teste)")
    s.add_argument("destino", help="ex.: teste (segredo email_destinatarios_teste) ou dono")
    s.add_argument("--adicionar", nargs="+", metavar="EMAIL")
    s.add_argument("--remover", nargs="+", metavar="EMAIL")
    s.set_defaults(fn=cmd_destinatarios)

    s = sub.add_parser("base-referencia", help="registra o estoque atual como já conhecido, sem enviar nada")
    s.add_argument("task")
    s.set_defaults(fn=cmd_base_referencia)

    s = sub.add_parser("resumo", help="resumo do estoque (7h/12h/14h/18h): e-mail completo + cartão no Teams")
    s.add_argument("task")
    s.add_argument("--real", action="store_true", help="envia e marca o resumo como feito")
    s.add_argument("--canais", help="envia só para estes canais, separados por vírgula (ex.: email:dono = só o seu e-mail); "
                                    "envio parcial não marca o resumo como feito")
    s.add_argument("--forcar-inativa", action="store_true")
    s.set_defaults(fn=cmd_resumo)

    s = sub.add_parser("simular", help="mostra os cartões e o e-mail com dados de EXEMPLO (--enviar posta no canal de teste)")
    s.add_argument("task", nargs="?", default="cds_gfw_fora_da_area")
    s.add_argument("--enviar", action="store_true", help="posta os cartões de exemplo no canal de teste do Teams")
    s.add_argument("--canal", default="teams:teste")
    s.set_defaults(fn=cmd_simular)

    s = sub.add_parser("doctor", help="confere o ambiente (chaves, segredos, BigQuery, Outlook, agendamentos)")
    s.add_argument("task", nargs="?", help="tarefa a considerar (ex.: cds_gfw_fora_da_area)")
    s.set_defaults(fn=cmd_doctor)

    s = sub.add_parser("atualizacoes", help="histórico das cargas detectadas na origem")
    s.add_argument("task")
    s.add_argument("--limite", type=int, default=30)
    s.set_defaults(fn=cmd_atualizacoes)

    s = sub.add_parser("status", help="heartbeat: alerta se o robô não rodou (código de saída 1)")
    s.add_argument("task")
    s.add_argument("--max-horas", type=float, default=26)
    s.set_defaults(fn=cmd_status)

    args = p.parse_args(argv)
    return args.fn(args) or 0


if __name__ == "__main__":
    sys.exit(main())
