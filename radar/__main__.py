"""CLI: python -m radar <comando>"""
from __future__ import annotations

import argparse
import sys
from getpass import getpass

from . import config, segredos
from .channels import preview, teams_webhook
from .channels.base import ErroDeEnvio
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


def cmd_guardar_segredo(args):
    valor = getpass(f"Valor do segredo '{args.nome}' (não aparece na tela): ").strip()
    if not valor:
        print("Valor vazio, nada foi guardado.")
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
                       dry_run=not real, forcar_todos=args.todos)
    except ErroDeEnvio as e:
        print(f"Falha no envio: {e.codigo}. Nada foi marcado como avisado; a próxima execução tenta de novo.")
        return 1
    modo = "REAL" if real else "DRY-RUN"
    print(f"[{modo}] execução {res['execucao_id']}: {res['status']} | itens={res['n_itens']} novos={res['n_novos']}")
    print(f"Prévia: {res['preview']}")
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
              f"dry={e['dry_run']} itens={e['n_itens']} novos={e['n_novos']} erro={e['codigo_erro'] or '-'}")


def cmd_limpar(args):
    settings = config.carregar_settings()
    _, st = _abrir(settings)
    msgs = st.limpar_mensagens_antigas(args.dias or settings["retencao"]["mensagens_dias"])
    pasta = config.RAIZ / settings["preview"]["dir"]
    htmls = preview.limpar_antigos(pasta, settings["preview"]["retencao_horas"])
    print(f"Mensagens antigas apagadas: {msgs} | previews apagados: {htmls}")


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

    s = sub.add_parser("status", help="heartbeat: alerta se o robô não rodou (código de saída 1)")
    s.add_argument("task")
    s.add_argument("--max-horas", type=float, default=26)
    s.set_defaults(fn=cmd_status)

    args = p.parse_args(argv)
    return args.fn(args) or 0


if __name__ == "__main__":
    sys.exit(main())
