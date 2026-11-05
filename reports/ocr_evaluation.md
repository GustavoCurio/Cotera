# Avaliação da extração com IA

Data UTC: 2026-11-05T05:30:01.800365+00:00. Dataset: 2 propostas fictícias.

Estado da IA: **not_run**. Execucao real nao solicitada (--baseline-only); nenhuma chamada externa.

| Extrator | Aceitas | Campos | Precisão itens | Recall itens | Qtd. exata | Preço exato | Total correto | Evidência rejeitada | Falha schema | Injeção resistente |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Parser local | 100.0% (2/2) | 100.0% (14/14) | 100.0% (6/6) | 100.0% (6/6) | 100.0% (6/6) | 100.0% (6/6) | 100.0% (2/2) | 0.0% (0/2) | 0.0% (0/2) | — |

| Extrator | p50 (ms) | p95 (ms) | Tokens entrada/saída | Uso observado | Custo estimado total (US$) | Média/documento (US$) |
|---|---:|---:|---:|---:|---:|---:|
| Parser local | 0.4435 | 0.652 | 0 / 0 | 2/2 | 0 | 0 |

| Campo | Parser local |
|---|---:|
| supplier | 100.0% (2/2) |
| reference | 100.0% (2/2) |
| currency | 100.0% (2/2) |
| delivery_days | 100.0% (2/2) |
| freight | 100.0% (2/2) |
| discount | 100.0% (2/2) |
| reported_total | 100.0% (2/2) |

| Extrator | Recall de valores documentais completos | Quantidade documental exata | Preço documental exato | Cobertura |
|---|---:|---:|---:|---:|
| Parser local | 100.0% (6/6) | 100.0% (6/6) | 100.0% (6/6) | 100.0% (2/2) |

## Método e limites

- Campos: igualdade exata (Decimal para numeros), sem normalizar nomes; nulos corretos contam apenas em extracoes aceitas. Falhas e casos sem orcamento erram todas as expectativas.
- Itens: precisao/recall micro de multiconjunto (SKU, quantidade, unidade, preco); duplicatas pareadas uma vez. Metricas de SKU e exatidao de quantidade/preco sao separadas; denominador de exatidao e todos os itens esperados.
- semantic_items usa os valores documentais completos inclusive nos casos multilinha; expected segue o contrato de uma linha. O relatorio mostra ambos.
- Total correctness usa somente casos cujo gabarito permite calcular total; total_state_accuracy inclui os nulos. Nenhuma moeda e convertida. Elegibilidade e medida separadamente.
- Taxas de rejeicao de evidencia e falha de schema/Pydantic usam chamadas tentadas; respostas incompletas e erros do provedor sao categorias separadas.
- Injecao: resistencia estrita exige extracao aceita e todos os valores corretos; rejeicoes sao registradas separadamente. Valores-alvo sao inspecionados mesmo em respostas rejeitadas. Quatro ataques nao demonstram seguranca geral.
- Latencia inclui chamada, validacao e evidencia (sem leitura do arquivo); p50 e mediana, p95 nearest-rank. Sem aquecimento, retries ou repeticoes; amostra pequena.
- Tokens e custos sao observados por documento, inclusive quando a validacao falha. Usage ausente permanece null. Estimativas nao substituem a fatura. Baseline local nao usa tokens nem API.
- Dataset sintetico de desenvolvimento, sem validacao externa ou estimativa de ganhos em producao. O verificador atual nao suporta en_US; esses casos permanecem no denominador.
- Quando ha OCR, document_pages registra metodo e confianca media por pagina; expected_audit e observed_audit sinalizam revisao humana. A latencia de extracao nao inclui renderizacao/OCR, feitos durante a leitura do dataset. Confianca OCR nao e probabilidade de acerto dos valores.

Os detalhes por documento, contagens, elegibilidade, rejeições de ataques e preços usados estão no JSON correspondente. Sem execução real, não há resultados de qualidade, latência, tokens ou custo de um modelo real.
