/* ================================================================
   CDS ABERTAS DA GFW FORA DA GFW
   - Pertence à GFW pela Classificacao / CT de origem
   - Está fora da GFW pelo CT Atual
   - Somente abertas
   - Uma linha por Nota QM
   - Premissas TURNBACK aplicadas
   ================================================================ */

WITH base AS (
  SELECT
    REGEXP_REPLACE(Nota_de_QM, r'^0+', '') AS Nota_QM,

    Tipo_de_Nota,
    Autor,

    Data_da_Nota,
    Hora_da_Nota,

    DATE_DIFF(
      CURRENT_DATE('America/Sao_Paulo'),
      Data_da_Nota,
      DAY
    ) AS Dias_em_Aberto,

    CASE
      WHEN DATE_DIFF(
        CURRENT_DATE('America/Sao_Paulo'),
        Data_da_Nota,
        DAY
      ) = 0
        THEN 'Hoje'

      WHEN DATE_DIFF(
        CURRENT_DATE('America/Sao_Paulo'),
        Data_da_Nota,
        DAY
      ) BETWEEN 1 AND 3
        THEN '1 a 3 dias'

      WHEN DATE_DIFF(
        CURRENT_DATE('America/Sao_Paulo'),
        Data_da_Nota,
        DAY
      ) BETWEEN 4 AND 7
        THEN '4 a 7 dias'

      WHEN DATE_DIFF(
        CURRENT_DATE('America/Sao_Paulo'),
        Data_da_Nota,
        DAY
      ) BETWEEN 8 AND 15
        THEN '8 a 15 dias'

      WHEN DATE_DIFF(
        CURRENT_DATE('America/Sao_Paulo'),
        Data_da_Nota,
        DAY
      ) BETWEEN 16 AND 30
        THEN '16 a 30 dias'

      ELSE 'Mais de 30 dias'
    END AS Faixa_de_Atraso,

    Centro,

    Item_Codificacao AS Aplic,
    Item_Codigo AS SubAplic,
    Descricao AS Descricao_SubAplic,

    SAFE_CAST(
      REGEXP_EXTRACT(
        UPPER(TRIM(COALESCE(Item_Codificacao, ''))),
        r'(\d+)'
      ) AS INT64
    ) AS aplic_n,

    SAFE_CAST(
      REGEXP_EXTRACT(
        TRIM(COALESCE(Item_Codigo, '')),
        r'(\d+)'
      ) AS INT64
    ) AS sub_n,

    /* CT de origem / classificação: identifica que a CD é da GFW */
    Classificacao AS ID_CT_Origem,
    Num_Classificacao AS Numero_CT_Origem,
    Desc_Classificacao AS Descricao_CT_Origem,

    /* CT atual: identifica onde a CD está agora */
    CT_Atual AS ID_CT_Atual,
    Num_CT_Atual AS Numero_CT_Atual,
    Desc_CT_Atual AS Descricao_CT_Atual,

    Area_Responsavel,
    Descricao_Area_Responsavel,

    Local_Da_Instacalao AS Local_de_Instalacao,
    Programa,
    Programa_Produto,

    CASE
      WHEN STARTS_WITH(
        TRIM(COALESCE(Local_Da_Instacalao, '')),
        '0170'
      )
        THEN 'EJETS E1'

      WHEN STARTS_WITH(
        TRIM(COALESCE(Local_Da_Instacalao, '')),
        '0190'
      )
        THEN 'EJETS E2'

      ELSE 'Outros'
    END AS Modelo_Aeronave,

    CASE
      WHEN STRPOS(
        TRIM(COALESCE(Local_Da_Instacalao, '')),
        '-'
      ) > 0
        THEN SPLIT(
          TRIM(Local_Da_Instacalao),
          '-'
        )[SAFE_OFFSET(1)]

      ELSE Numero_de_Serie_Aeronave
    END AS Serial_Exibicao,

    Numero_de_Serie_Aeronave,

    Descricao_do_Problema,

    Tipo_Defeito,
    Codigo_Defeito,
    Descricao_do_Tipo_de_Defeito,

    Material,
    PN,
    Descricao_do_Material,

    Codigo_do_Grupo,
    Item_do_Grupo,
    Descricao_do_Item_do_Grupo AS Causa,

    Doc_Ref_Sgl AS Tipo_Documento_Referencia,
    Doc_Ref_Num AS Numero_Documento_Referencia,

    Fornecedor,
    Descricao_Fornecedor,

    OP,
    Ordem_de_QM,

    Status_do_Sistema_Nota,

    CASE
      WHEN Status_do_Sistema_Nota = 'I0070'
        THEN 'Aberta'

      WHEN Status_do_Sistema_Nota = 'I0072'
        THEN 'Encerrada'

      ELSE Status_do_Sistema_Nota
    END AS Status,

    Responsavel_Proxima_Acao,
    Nome_do_Responsavel_Proxima_Acao,

    Fluxo,
    Grupo_Code,
    Code,
    Descricao_Code_Medida,
    Texto_da_Medida,

    Data_Criacao_Medida,
    Hora_Criacao_Medida,

    Data_Alteracao_Medida,
    Hora_Alteracao_Medida,

    Data_Plan_Inicio,
    Hora_Plan_Inicio,
    Data_Plan_Final,
    Hora_Plan_Final,

    Dias_sem_Fluxo,
    Horas_sem_Fluxo,

    /* Verifica se qualquer medida da nota é NFF */
    COALESCE(
      LOGICAL_OR(
        UPPER(TRIM(COALESCE(Grupo_Code, ''))) = 'CDDISQUA'
        AND UPPER(TRIM(COALESCE(Code, ''))) = 'NFF'
      ) OVER (
        PARTITION BY Nota_de_QM
      ),
      FALSE
    ) AS tem_medida_nff,

    ROW_NUMBER() OVER (
      PARTITION BY Nota_de_QM
      ORDER BY
        Data_Criacao_Medida DESC,
        Hora_Criacao_Medida DESC
    ) AS numero_linha

  FROM
    `emb-prd-it-data-lakehouse-d8ff.opp_intermediate.consolidated_zqlrqm150_medidas`

  WHERE Centro = 'SJK1'

    AND Tipo_de_Nota = 'CD'

    /* A CD pertence à GFW pelo CT de origem/classificação */
    AND Classificacao IN (
      '10024696',
      '10015205',
      '10010172',
      '10010866',
      '10015208'
    )

    /* Mas o CT atual está fora dos cinco CTs da GFW */
    AND (
      CT_Atual IS NULL
      OR TRIM(CT_Atual) = ''
      OR CT_Atual NOT IN (
        '10024696',
        '10015205',
        '10010172',
        '10010866',
        '10015208'
      )
    )

    /* Apenas CDs abertas */
    AND Status_do_Sistema_Nota = 'I0070'
),

notas_deduplicadas AS (
  SELECT
    *
  FROM base
  WHERE numero_linha = 1
),

prep AS (
  SELECT
    *,

    UPPER(
      TRIM(
        COALESCE(Tipo_Documento_Referencia, '')
      )
    ) AS u_docref,

    UPPER(
      TRIM(
        COALESCE(Causa, '')
      )
    ) AS u_itemgrupo,

    UPPER(
      TRIM(
        COALESCE(Descricao_do_Problema, '')
      )
    ) AS u_problema,

    UPPER(
      TRIM(
        COALESCE(Descricao_do_Material, '')
      )
    ) AS u_material,

    UPPER(
      TRIM(
        COALESCE(Descricao_do_Tipo_de_Defeito, '')
      )
    ) AS u_tipodefeito,

    UPPER(
      TRIM(
        COALESCE(Descricao_CT_Origem, '')
      )
    ) AS u_ctorigem,

    UPPER(
      TRIM(
        COALESCE(Numero_CT_Origem, '')
      )
    ) AS u_numclass,

    FORMAT(
      '%d-%d',
      aplic_n,
      sub_n
    ) AS aplic_sub

  FROM notas_deduplicadas
),

regras AS (
  SELECT
    *,

    CASE
      /* 1 - CDs duplicadas */
      WHEN (
        aplic_n IN (2, 13)
        AND u_docref IN ('CD', 'NC')
      )
      OR (
        aplic_n IN (7, 18)
        AND CONTAINS_SUBSTR(u_docref, 'CD')
      )
        THEN '1 - CD duplicada'

      /* 2.1 - Ferramental */
      WHEN aplic_n IN (4, 5, 11)
        OR CONTAINS_SUBSTR(u_itemgrupo, 'TOOL')
        THEN '2.1 - Ferramental'

      /* 2.2 - Efetividade / revalidação / obsoleto */
      WHEN aplic_n = 9
        THEN '2.2 - Efetividade'

      /* 3 - Falta de material */
      WHEN aplic_sub IN (
        '1-2',
        '2-6',
        '3-4',
        '10-2',
        '10-17',
        '12-12',
        '13-14',
        '15-13',
        '17-17'
      )
      OR CONTAINS_SUBSTR(u_itemgrupo, 'SUPPLY')
        THEN '3 - Falta de Material'

      /* 4 - Protótipo / corpo de prova */
      WHEN CONTAINS_SUBSTR(u_material, 'CORPO PROVA')
        OR CONTAINS_SUBSTR(u_problema, 'CORPO PROVA')
        THEN '4 - Protótipo'

      /* 5 - Phase-out */
      WHEN aplic_sub = '7-7'
        THEN '5 - Phase-out'

      /* 5.1 - Decisão de Programa */
      WHEN aplic_n = 7
        AND CONTAINS_SUBSTR(u_itemgrupo, 'PROGRAMA')
        THEN '5.1 - Decisão de Programa'

      /* 6 - NFF */
      WHEN tem_medida_nff
        OR CONTAINS_SUBSTR(u_ctorigem, 'NFF')
        OR CONTAINS_SUBSTR(u_numclass, 'NFF')
        THEN '6 - NFF'

      /* 7 - Canibalização */
      WHEN (
        aplic_sub = '2-3'
        AND REGEXP_CONTAINS(
          u_problema,
          r'CANNIBAL|CANIBAL|CANBLZ|CNBLZ|CANIB|CANIBALIZATION|CANIBALIZACAO|CANIBALIZAÇÃO|CAN-'
        )
      )
      OR aplic_sub = '3-5'
      OR REGEXP_CONTAINS(
        u_tipodefeito,
        r'CANIBALIZ'
      )
        THEN '7 - Canibalização'

      /* 8 - Aplicações especiais */
      WHEN aplic_n IN (
        14,
        20,
        21,
        23,
        28,
        30,
        32,
        33,
        34,
        36,
        37
      )
        THEN '8 - Especial'

      /* 10 - Logística / Planning */
      WHEN CONTAINS_SUBSTR(u_itemgrupo, 'LOG')
        OR CONTAINS_SUBSTR(u_itemgrupo, 'PLAN')
        THEN '10 - Logística'

      ELSE NULL
    END AS MotivoExclusao

  FROM prep
)

SELECT
  Nota_QM,
  Data_da_Nota,
  Hora_da_Nota,
  Dias_em_Aberto,
  Faixa_de_Atraso,

  Status,

  Aplic,
  SubAplic,
  Descricao_SubAplic,

  ID_CT_Origem,
  Numero_CT_Origem,
  Descricao_CT_Origem,

  ID_CT_Atual,
  Numero_CT_Atual,
  Descricao_CT_Atual,

  Area_Responsavel,
  Descricao_Area_Responsavel,

  Local_de_Instalacao,
  Modelo_Aeronave,
  Serial_Exibicao,
  Programa,
  Programa_Produto,

  Descricao_do_Problema,
  Tipo_Defeito,
  Codigo_Defeito,
  Descricao_do_Tipo_de_Defeito,

  Material,
  PN,
  Descricao_do_Material,

  Codigo_do_Grupo,
  Item_do_Grupo,
  Causa,

  Tipo_Documento_Referencia,
  Numero_Documento_Referencia,

  Fornecedor,
  Descricao_Fornecedor,

  OP,
  Ordem_de_QM,

  Responsavel_Proxima_Acao,
  Nome_do_Responsavel_Proxima_Acao,

  Fluxo,
  Grupo_Code,
  Code,
  Descricao_Code_Medida,
  Texto_da_Medida,

  Data_Criacao_Medida,
  Hora_Criacao_Medida,

  Data_Plan_Inicio,
  Hora_Plan_Inicio,
  Data_Plan_Final,
  Hora_Plan_Final,

  Dias_sem_Fluxo,
  Horas_sem_Fluxo

FROM regras

/* Mantém apenas registros válidos pelas premissas TURNBACK */
WHERE MotivoExclusao IS NULL

/* Pendências mais antigas primeiro */
ORDER BY
  Data_da_Nota ASC,
  Hora_da_Nota ASC,
  Nota_QM ASC
