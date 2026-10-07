import json
from datetime import date, datetime, time, timedelta, timezone

from radar.channels import email_conteudo as ec
from radar.channels import teams_webhook
from radar.engine import sinais
from radar.engine.resumo import executar_resumo
from radar.engine.runner import executar
from tests.conftest import FonteFalsa

AGORA = datetime(2026, 10, 7, 14, 0)
CFG = {
    "fuso": "America/Sao_Paulo", "campos_resumo": ["Modelo_Aeronave", "Serial_Exibicao", "Descricao_CT_Atual"],
    "parada": {"ativo": True, "campo": "Dias_sem_Fluxo", "limite_dias": 7},
    "plano": {"ativo": True, "campo_fim": "Data_Plan_Final", "campo_hora_fim": "Hora_Plan_Final"},
    "sem_responsavel": {"ativo": True, "campos": ["Responsavel_Proxima_Acao", "Nome_do_Responsavel_Proxima_Acao"]},
    "vazamento": {"ativo": True, "origem": "Descricao_CT_Origem"},
}


def cd(nota, sem_fluxo=1, fim=date(2026, 12, 1), hora=time(10, 0), resp="X1", nome="Fulano", origem="JUNCAO", dias=5):
    return {"Nota_QM": nota, "Dias_sem_Fluxo": sem_fluxo, "Data_Plan_Final": fim, "Hora_Plan_Final": hora,
            "Responsavel_Proxima_Acao": resp, "Nome_do_Responsavel_Proxima_Acao": nome,
            "Descricao_CT_Origem": origem, "Descricao_CT_Atual": "HANGAR", "Modelo_Aeronave": "EJETS E2",
            "Serial_Exibicao": "001", "Dias_em_Aberto": dias, "Faixa_de_Atraso": "4 a 7 dias"}


def itens(s, nome):
    return [i["nota"] for i in s[nome]["itens"]]


def test_parada_usa_dias_sem_fluxo_e_nao_dias_em_aberto():
    est = [cd("1", sem_fluxo=7, dias=40), cd("2", sem_fluxo=6, dias=40), cd("3", sem_fluxo=20, dias=1)]
    s = sinais.calcular(est, CFG, "Nota_QM", AGORA)
    assert itens(s, "parada") == ["3", "1"]  # mais parada primeiro; a 2 (aberta há 40, mexida ontem) fica de fora
    assert s["parada"]["limite"] == 7


def test_plano_vencido_considera_data_e_hora():
    est = [cd("1", fim=date(2026, 10, 6)),                           # venceu ontem
           cd("2", fim=date(2026, 10, 7), hora=time(9, 0)),          # hoje, hora já passou
           cd("3", fim=date(2026, 10, 7), hora=time(18, 0)),         # hoje, ainda no prazo
           cd("4", fim=date(2026, 12, 1))]
    s = sinais.calcular(est, CFG, "Nota_QM", AGORA)
    assert sorted(itens(s, "plano_vencido")) == ["1", "2"]
    assert "venceu há 1 dia" in s["plano_vencido"]["itens"][0]["detalhe"]


def test_sem_plano_inclui_datas_vazias_do_sap():
    est = [cd("1", fim=None), cd("2", fim=date(1, 1, 1)), cd("3", fim=date(9999, 12, 31)), cd("4", fim="0000-00-00"),
           cd("5")]
    s = sinais.calcular(est, CFG, "Nota_QM", AGORA)
    assert sorted(itens(s, "sem_plano")) == ["1", "2", "3", "4"] and itens(s, "plano_vencido") == []


def test_sem_responsavel_exige_todos_os_campos_vazios():
    est = [cd("1", resp="", nome=None), cd("2", resp="", nome="Fulano"), cd("3", resp="X", nome=None),
           cd("4", resp="0", nome=" ")]
    assert sorted(itens(sinais.calcular(est, CFG, "Nota_QM", AGORA), "sem_responsavel")) == ["1", "4"]


def test_sinal_desligado_nao_aparece():
    cfg = {**CFG, "parada": {"ativo": False, "campo": "Dias_sem_Fluxo"}}
    assert "parada" not in sinais.calcular([cd("1", sem_fluxo=99)], cfg, "Nota_QM", AGORA)


def test_marcas_juntam_os_sinais_de_cada_cd():
    est = [cd("1", sem_fluxo=10, fim=None), cd("2")]
    m = sinais.marcas(sinais.calcular(est, CFG, "Nota_QM", AGORA))
    assert m == {"1": ["PARADA 10d", "SEM PLANO"]}


def test_vazamento_por_ct_de_origem():
    agora = datetime.now(timezone.utc)
    est = [cd("1", origem="JUNCAO", dias=10), cd("2", origem="JUNCAO", dias=20), cd("3", origem="PINTURA", dias=4)]
    quando = lambda d: (agora - timedelta(days=d)).isoformat(timespec="seconds")
    entradas = [{"quando": quando(2), "chave": "1", "Descricao_CT_Origem": "JUNCAO"},
                {"quando": quando(20), "chave": "2"},                       # registro antigo: origem vem do estoque
                {"quando": quando(60), "chave": "3", "Descricao_CT_Origem": "PINTURA"}]  # fora da janela
    resolvidas = [{"quando": quando(3), "origem": "PINTURA"}, {"quando": quando(90), "origem": "PINTURA"}]
    v = {r["ct"]: r for r in sinais.vazamento(est, entradas, resolvidas, CFG, "Nota_QM", agora)}
    assert v["JUNCAO"]["abertas"] == 2 and v["JUNCAO"]["media_dias"] == 15.0 and v["JUNCAO"]["percentual"] == 67
    assert (v["JUNCAO"]["entraram_7d"], v["JUNCAO"]["entraram_30d"]) == (1, 2)
    assert v["PINTURA"]["entraram_30d"] == 0 and v["PINTURA"]["resolvidas_30d"] == 1


def test_dados_estranhos_nao_quebram():
    est = [{"Nota_QM": "1", "Dias_sem_Fluxo": "abc", "Data_Plan_Final": 12345, "Hora_Plan_Final": "lixo",
            "Responsavel_Proxima_Acao": None, "Nome_do_Responsavel_Proxima_Acao": None, "Descricao_CT_Origem": None}]
    s = sinais.calcular(est, CFG, "Nota_QM", AGORA)
    assert itens(s, "sem_plano") == ["1"] and itens(s, "sem_responsavel") == ["1"] and itens(s, "parada") == []


# ------------------------------------------------------------------ integração
def tarefa(canais=("preview",)):
    return {
        "id": "t1", "modo": "novas", "canais": list(canais), "sinais": CFG,
        "fonte": {"campo_chave": "Nota_QM"},
        "mensagem": {"titulo": "x", "campos_exibidos": ["Nota_QM", "Descricao_CT_Atual"]},
        "acompanhamento": {"campos_criticos": ["Descricao_CT_Atual"], "campos_resumo": ["Modelo_Aeronave"],
                           "campos_snapshot": ["Nota_QM", "Descricao_CT_Origem", "Descricao_CT_Atual"]},
    }


def estoque_exemplo():
    return [cd("1", sem_fluxo=12, fim=date(2026, 1, 1)), cd("2", fim=None, resp="", nome=None), cd("3")]


def test_coluna_ausente_para_o_sinal_falha_com_schema_mudou(storage, crypto, settings):
    import pytest

    from radar.engine.runner import ErroDeTarefa

    est = [{k: v for k, v in l.items() if k != "Dias_sem_Fluxo"} for l in estoque_exemplo()]
    with pytest.raises(ErroDeTarefa):
        executar(tarefa(), FonteFalsa(est), storage, crypto, settings, dry_run=True)


def test_alerta_guarda_a_origem_para_o_vazamento(storage, crypto, settings):
    executar(tarefa(), FonteFalsa(estoque_exemplo()), storage, crypto, settings, dry_run=False)
    registros = storage.alertas_desde("t1", "2000-01-01T00:00:00+00:00")
    assert {r["Descricao_CT_Origem"] for r in registros} == {"JUNCAO"}


def test_resumo_traz_sinais_marcas_e_vazamento(storage, crypto, settings, tmp_path):
    s = {**settings, "sandbox": {"ativo": True, "canais_permitidos": ["preview", "teams:teste", "email:teste"]}}
    t = tarefa(("preview", "teams:teste", "email:teste"))
    t["email"] = {}
    enviados = {}
    executar_resumo(t, FonteFalsa(estoque_exemplo()), storage, crypto, s, dry_run=False,
                    enviadores={"teams:teste": lambda m: enviados.update(teams=m),
                                "email:teste": lambda m: enviados.update(email=m)})
    m = enviados["email"]
    assert m["sinais"]["parada"]["total"] == 1 and m["marcas"]["2"] == ["SEM PLANO", "SEM RESP."]
    assert m["vazamento"][0]["ct"] == "JUNCAO"
    html = ec.renderizar_html(m, "x.png")
    assert "Pontos de atenção" in html and "De onde saem as CDs" in html and "Paradas" in html
    card = teams_webhook.montar_payload(enviados["teams"])
    texto = json.dumps(card, ensure_ascii=False)
    assert "Pontos de atenção" in texto and "De quais CTs da GFW" in texto
    assert len(texto.encode()) <= 24_500


def test_excel_e_tabela_trazem_a_coluna_atencao(tmp_path):
    from openpyxl import load_workbook

    est = estoque_exemplo()
    s = sinais.calcular(est, CFG, "Nota_QM", AGORA)
    m = {"titulo": "T", "marca": "R", "dados_de": "x", "sandbox": False, "colunas": ["Nota_QM"], "rotulos": {},
         "estoque": est, "itens": [est[2]], "campo_chave": "Nota_QM", "marcas": sinais.marcas(s),
         "email": {"colunas_tabela": ["Nota_QM", "Dias_em_Aberto"]}}
    ec.gerar_xlsx(m, tmp_path / "x.xlsx")
    ws = load_workbook(tmp_path / "x.xlsx").active
    cabecalho = [c.value for c in ws[1]]
    assert cabecalho[1] == "Atenção"
    linha1 = [c.value for c in ws[2]]
    assert "PARADA 12d" in linha1[1] and ws["B2"].fill.fgColor.rgb.endswith("FFF3CD")
    arq = ec.gerar_arquivos(m, tmp_path, "t")
    assert arq["png"].read_bytes()[:4] == b"\x89PNG"
