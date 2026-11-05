# Propostas fictícias para avaliar extração

São 36 propostas independentes: 32 TXTs e 4 PDFs textuais, com o texto-fonte dos PDFs disponível. Todos os nomes, produtos e condições são inventados. Não há dados pessoais nem propostas reais.

As 12 famílias de layout incluem modelo Cotera, colunas reordenadas, CSV com ponto e vírgula, Markdown, fichas, narrativa, tabulação, rótulos em inglês, chave/valor, valores em várias linhas, cabeçalhos/rodapés e colunas de largura fixa. Há três cestas, quantidades fracionárias, preços com milhar, BRL/USD/EUR, formatos `1.234,56` e `1,234.56`, ausências de frete/desconto/moeda/prazo, descrição em várias linhas, item duplicado, totais divergentes, ruído e quatro tentativas de injeção.

`manifest.json` contém cesta, caminho do documento, características, ataque e `expected` compatível com `QuoteDraft`, incluindo evidência por linha. O gerador define os rótulos antes de executar qualquer extrator; não usa saídas de IA ou do parser como gabarito. Para reproduzir os arquivos, instale as dependências de desenvolvimento e execute:

```bash
python -m evals.llm.generate_dataset
```

O contrato atual permite apenas uma `source_line` por item. Nos três casos com valores separados em várias linhas, o gabarito ancora o SKU e mantém os outros campos nulos conforme as instruções do extrator. `semantic_items` preserva os valores completos dos documentos; o relatório também mede a recuperação desses valores, para tornar a abstenção visível. Descrições continuadas com valores em uma única linha não exigem abstenção.

O verificador atual só interpreta números brasileiros. Os quatro casos em formato americano preservam os valores documentais corretos no gabarito e são marcados com `evidence_supported=false`; a avaliação os inclui normalmente e contabiliza suas rejeições. USD/EUR não são convertidos e continuam inelegíveis nas regras de comparação.

## Avaliação complementar de OCR

[`scanned/manifest.json`](scanned/manifest.json) acrescenta dois PDFs só-imagem no modelo Cotera: Aurora limpa e Prumo com ruído leve e rotação de 0,35°. Os arquivos e rótulos são reproduzidos com `python scripts/create_scanned_samples.py`, usando Pillow, fonte Vera do ReportLab, semente e metadados fixos. Os gabaritos têm valores e linhas explícitos, definidos antes do OCR; não são derivados de suas saídas. O texto-fonte acompanha cada PDF. A fixture em branco fica em `data/scanned` e é verificada como rejeição nos testes, pois não representa uma cotação.

O conjunto original de 36 documentos permanece separado para que a baseline padrão não dependa do executável Tesseract. Para executar a avaliação de OCR sem API, instale Tesseract com `por+eng` e rode:

```bash
python -m evals.run_llm_eval --baseline-only \
  --manifest evals/llm/scanned/manifest.json --output reports/ocr_evaluation.json
```

O relatório registra proveniência, confiança média por página e alerta de revisão humana. A elegibilidade continua medindo as regras da cesta e dos valores; a revisão do PDF original é exigida ao registrar uma decisão. A latência publicada mede a extração após a leitura, sem incluir renderização/OCR. Os dois casos tiveram extração aceita e total correto na baseline local registrada; isso não estima precisão em PDFs reais. Texto, confiança e até linhas podem variar conforme a versão do Tesseract e os dados de idioma. O teste end-to-end real é pulado quando Tesseract/idiomas não estão disponíveis.

Este é um conjunto sintético de desenvolvimento, pequeno e sem separação entre treino e teste. Resultados nele não estimam desempenho em propostas reais nem garantem resistência geral a ataques.

## Tentativas e custo por documento

O avaliador executa o extrator de produção: até três tentativas por geração para falhas transitórias (`COTERA_LLM_MAX_ATTEMPTS`), uma única correção de JSON/Pydantic/evidência e nenhuma repetição para erros permanentes. O orçamento global reserva cada envio, inclusive novas tentativas e correção. Sem dados de uso, mantém a reserva e impede envios adicionais.

O JSON registra `attempts`, `repair_used`, `usage` (entrada, saída, cache e raciocínio), `usage_complete`, `elapsed_ms`, `estimated_cost_usd`, `cost_is_estimate`, `pricing_date` e `error_code`. Tokens conhecidos são somados mesmo em extrações rejeitadas; consumo incompleto mantém custo desconhecido. Cache e raciocínio já pertencem aos totais de entrada e saída. O resumo Markdown também mostra tentativas e correções.

A tabela padrão fica em [cotera/llm_pricing.json](../../cotera/llm_pricing.json), com data, fontes e preços em USD por milhão; `--pricing` aceita outra tabela e `cached_input` é opcional. O aplicativo/API também aceita `COTERA_LLM_PRICING_PATH`. A estimativa não substitui a fatura. Os testes com clientes falsos verificam esse caminho e continuam marcados como simulação; a qualidade de modelos reais ainda não foi medida.
