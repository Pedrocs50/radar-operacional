from datetime import datetime, timedelta, timezone

from radar.channels import email_conteudo as ec
from radar.channels import grafico, teams_webhook
from radar.engine import indicadores
from radar.engine.runner import executar
from tests.conftest import FonteFalsa

# quarta-feira, 7/10/2026 14:00 (a semana corrente começa na segunda, 5/10)
AGORA = datetime(2026, 10, 7, 14, 0).astimezone()


def q(dias_atras, **extra):
    return {"quando": (AGORA - timedelta(days=dias_atras)).isoformat(timespec="seconds"), **extra}


def test_janelas_semanas_e_tempo_para_resolver():
    entradas = [q(0), q(1), q(3), q(10), q(40)]
    saidas = [q(1, dias="10"), q(5, dias="20"), q(20, dias="30"), q(40, dias=None)]
    r = indicadores.calcular(entradas, saidas, AGORA, semanas=8)
    j7, j30 = r["janelas"]["7d"], r["janelas"]["30d"]
    assert (j7["entradas"], j7["saidas"], j7["saldo"]) == (3, 2, 1)
    assert (j30["entradas"], j30["saidas"]) == (4, 3) and j30["tempo_medio"] == 20.0 and j30["tempo_mediano"] == 20
    assert j30["amostra"] == 3
    assert len(r["semanas"]) == 8 and r["semanas"][-1]["parcial"] and r["semanas"][-1]["rotulo"] == "05/10"
    assert sum(s["entradas"] for s in r["semanas"]) == 5 and r["tem_dados"]


def test_sem_historico_nao_quebra():
    r = indicadores.calcular([], [], AGORA)
    assert not r["tem_dados"] and r["janelas"]["30d"]["tempo_medio"] is None


def test_a_base_de_referencia_nao_conta_como_entrada(storage, crypto, settings):
    task = {"id": "t1", "modo": "novas", "canais": ["preview"], "indicadores": {"ativo": True, "semanas": 4},
            "fonte": {"campo_chave": "Nota"},
            "mensagem": {"titulo": "x", "campos_exibidos": ["Nota"]}}
    linhas = lambda *n: [{"Nota": x} for x in n]
    executar(task, FonteFalsa(linhas("1", "2", "3")), storage, crypto, settings, dry_run=False)   # base de referência
    executar(task, FonteFalsa(linhas("1", "2", "3", "4")), storage, crypto, settings, dry_run=False)  # 1 entrada real
    r = indicadores.preparar(task, storage)["indicadores"]
    assert r["janelas"]["30d"]["entradas"] == 1
    assert indicadores.preparar({"id": "t1"}, storage) == {}  # sem `indicadores:` no YAML não calcula nada


def test_grafico_png_e_email_com_resultados(tmp_path):
    ind = indicadores.calcular([q(0), q(8)], [q(1, dias="7")], AGORA, 6)
    assert grafico.gerar(ind["semanas"], tmp_path / "g.png").read_bytes()[:4] == b"\x89PNG"
    est = [{"Nota_QM": "1", "Dias_em_Aberto": 3, "Descricao_CT_Atual": "X", "Modelo_Aeronave": "E2"}]
    m = {"tipo": "resumo", "titulo": "R", "marca": "R", "dados_de": "x", "sandbox": False, "colunas": ["Nota_QM"],
         "rotulos": {}, "estoque": est, "itens": [], "campo_chave": "Nota_QM", "indicadores": ind,
         "geral": ec.visao_geral(est, ec.CAMPOS_PADRAO, "Nota_QM"), "eventos": [], "desde_texto": "x", "resolvidas_7d": 0,
         "periodo": {"novas": 0, "resolvida": 0, "voltou_gfw": 0, "mudou_ct": 0, "saiu_criterio": 0, "nao_encontrada": 0}}
    html = ec.renderizar_html(m, "t.png", "cid:grafico")
    assert "Resultados" in html and 'src="cid:grafico"' in html and "Saldo (7 dias)" in html
    assert ec.gerar_arquivos({**m, "email": {}}, tmp_path, "t")["grafico"].exists()


def test_cartao_do_resumo_mostra_resultados():
    ind = indicadores.calcular([q(0)], [q(1, dias="9")], AGORA)
    m = {"tipo": "resumo", "titulo": "R", "marca": "R", "dados_de": "x", "desde_texto": "x",
         "geral": {"total": 1, "mais_antiga_dias": 1, "mais_antiga_nota": "1", "media_dias": 1, "faixas": [], "modelos": []},
         "periodo": {"novas": 0, "resolvida": 0, "voltou_gfw": 0, "mudou_ct": 0}, "indicadores": ind}
    texto = str(teams_webhook.montar_payload(m))
    assert "Resultados" in texto and "Tempo para resolver" in texto and "9.0 dias" in texto


# ------------------------------------------------------------------ painéis do relatório diário
def test_contagem_ordena_agrupa_e_junta_o_resto_em_outros():
    from radar.engine import paineis

    est = [{"ct": "A"}] * 5 + [{"ct": "B"}] * 3 + [{"ct": None}] * 2 + [{"ct": " "}] + [{"ct": "C"}, {"ct": "D"}, {"ct": "E"}]
    linhas = paineis.contar(est, "ct", top=3)
    assert linhas[0] == ("A", 5, False) and linhas[1] == ("B", 3, False)
    assert linhas[2] == ("(sem informação)", 3, False)
    assert linhas[3] == ("Outros (3)", 3, True)  # C, D e E somados
    assert sum(n for _, n, _ in linhas) == len(est)


def test_paineis_so_com_graficos_ativos():
    from radar.engine import paineis

    est = [{"ct": "A"}]
    cfg = {"ativo": True, "top": 5, "paineis": [{"titulo": "T", "campo": "ct"}]}
    assert paineis.preparar({"graficos": cfg}, est)["paineis"][0]["linhas"] == [("A", 1, False)]
    assert paineis.preparar({}, est) == {} and paineis.preparar({"graficos": {**cfg, "ativo": False}}, est) == {}
    assert paineis.colunas_necessarias(cfg) == ["ct"] and paineis.colunas_necessarias(None) == []


def test_painel_png_email_e_cartao(tmp_path):
    from radar.engine import paineis

    est = [{"Nota_QM": str(i), "Dias_em_Aberto": 3, "Modelo_Aeronave": "E2", "Descricao_CT_Atual": f"CT {i % 3}",
            "x": "d"} for i in range(9)]
    cfg = {"ativo": True, "top": 5, "paineis": [{"titulo": "Onde estão", "campo": "Descricao_CT_Atual"},
                                                {"titulo": "Tipo", "campo": "x"}]}
    p = paineis.preparar({"graficos": cfg}, est)
    m = {"tipo": "resumo", "titulo": "R", "marca": "R", "dados_de": "x", "sandbox": False, "colunas": ["Nota_QM"],
         "rotulos": {}, "estoque": est, "itens": [], "campo_chave": "Nota_QM", **p,
         "geral": ec.visao_geral(est, ec.CAMPOS_PADRAO, "Nota_QM"), "eventos": [], "desde_texto": "x", "resolvidas_7d": 0,
         "periodo": {"novas": 0, "resolvida": 0, "voltou_gfw": 0, "mudou_ct": 0, "saiu_criterio": 0, "nao_encontrada": 0}}
    assert ec.gerar_arquivos({**m, "email": {}}, tmp_path, "t")["painel"].read_bytes()[:4] == b"\x89PNG"
    html = ec.renderizar_html(m, "t.png", None, "cid:painel")
    assert "Onde estão as CDs abertas" in html and 'src="cid:painel"' in html and "maior grupo" in html
    assert "Onde estão" in str(teams_webhook.montar_payload(m))   # o cartão leva só texto, sem imagem


def test_alerta_de_cd_nova_nao_leva_graficos(tmp_path):
    est = [{"Nota_QM": "1", "Dias_em_Aberto": 3, "Modelo_Aeronave": "E2", "Descricao_CT_Atual": "X"}]
    m = {"titulo": "A", "marca": "R", "dados_de": "x", "sandbox": False, "colunas": ["Nota_QM"], "rotulos": {},
         "estoque": est, "itens": est, "campo_chave": "Nota_QM", "email": {}}
    arq = ec.gerar_arquivos(m, tmp_path, "t")
    assert "painel" not in arq and "grafico" not in arq
