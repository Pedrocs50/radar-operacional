/* Situação atual de CDs que saíram da lista "abertas da GFW fora da área".
   Usada só para explicar por que sumiram: encerrada, voltou para a GFW ou saiu das premissas.
   Recebe o parâmetro @notas (lista de Nota QM sem zeros à esquerda). Lê poucas colunas. */
WITH ultimas AS (
  SELECT
    REGEXP_REPLACE(Nota_de_QM, r'^0+', '') AS Nota_QM,
    Status_do_Sistema_Nota,
    CT_Atual,
    Desc_CT_Atual,
    ROW_NUMBER() OVER (
      PARTITION BY Nota_de_QM
      ORDER BY Data_Criacao_Medida DESC, Hora_Criacao_Medida DESC
    ) AS numero_linha
  FROM
    `emb-prd-it-data-lakehouse-d8ff.opp_intermediate.consolidated_zqlrqm150_medidas`
  WHERE Centro = 'SJK1'
    AND Tipo_de_Nota = 'CD'
    AND REGEXP_REPLACE(Nota_de_QM, r'^0+', '') IN UNNEST(@notas)
)
SELECT Nota_QM, Status_do_Sistema_Nota, CT_Atual, Desc_CT_Atual
FROM ultimas
WHERE numero_linha = 1
