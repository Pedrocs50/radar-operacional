WITH base AS (
  SELECT
    Nota_de_QM,
    Data_da_Nota,
    Descricao_do_Problema,
    Item_Codificacao,
    Desc_CT_Atual,
    Desc_Classificacao,
    Local_Da_Instacalao,
    Descricao_do_Tipo_de_Defeito,
    Descricao_do_Item_do_Grupo,
    Data_Criacao_Medida,
    Hora_Criacao_Medida,

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

    /* CT Atual da GFW */
    AND CT_Atual IN (
      '10024696',
      '10015205',
      '10010172',
      '10010866',
      '10015208'
    )

    /* Somente registros cuja origem/classificação seja Escape */
    AND CONTAINS_SUBSTR(
      UPPER(TRIM(COALESCE(Desc_Classificacao, ''))),
      'ESCAPE'
    )

    AND Status_do_Sistema_Nota IN (
      'I0070',
      'I0072'
    )
),

notas_deduplicadas AS (
  SELECT *
  FROM base
  WHERE numero_linha = 1
),

ultima_data AS (
  SELECT
    MAX(Data_da_Nota) AS data_mais_recente
  FROM notas_deduplicadas
)

SELECT
  REGEXP_REPLACE(
    n.Nota_de_QM,
    r'^0+',
    ''
  ) AS Nota,

  n.Descricao_do_Problema AS Descricao_do_Problema,

  n.Item_Codificacao AS Item_Codificacao,

  n.Desc_CT_Atual AS Desc_CT_Atual,

  n.Desc_Classificacao AS Desc_Classificacao,

  n.Local_Da_Instacalao AS NS_Aviao,

  n.Descricao_do_Tipo_de_Defeito AS Descricao_Tipo_Defeito,

  n.Data_da_Nota AS Data_da_CD

FROM notas_deduplicadas AS n

CROSS JOIN ultima_data AS u

WHERE n.Data_da_Nota = u.data_mais_recente

ORDER BY
  n.Data_da_Nota DESC,
  Nota DESC
