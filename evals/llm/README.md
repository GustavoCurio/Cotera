# Propostas fictícias para avaliar extração

São 36 propostas independentes: 32 TXTs e 4 PDFs textuais, com o texto-fonte dos PDFs disponível. Todos os nomes, produtos e condições são inventados. Não há dados pessoais nem propostas reais.

As 12 famílias de layout incluem modelo Cotera, colunas reordenadas, CSV com ponto e vírgula, Markdown, fichas, narrativa, tabulação, rótulos em inglês, chave/valor, valores em várias linhas, cabeçalhos/rodapés e colunas de largura fixa. Há três cestas, quantidades fracionárias, preços com milhar, BRL/USD/EUR, formatos `1.234,56` e `1,234.56`, ausências de frete/desconto/moeda/prazo, descrição em várias linhas, item duplicado, totais divergentes, ruído e quatro tentativas de injeção.

`manifest.json` contém cesta, caminho do documento, características, ataque e `expected` compatível com `QuoteDraft`, incluindo evidência por linha. O gerador define os rótulos antes de executar qualquer extrator; não usa saídas de IA ou do parser como gabarito. Para reproduzir os arquivos, instale as dependências de desenvolvimento e execute:

```bash
python -m evals.llm.generate_dataset
```

O contrato atual permite apenas uma `source_line` por item. Nos três casos com valores separados em várias linhas, o gabarito ancora o SKU e mantém os outros campos nulos conforme as instruções do extrator. `semantic_items` preserva os valores completos dos documentos; o relatório também mede a recuperação desses valores, para tornar a abstenção visível. Descrições continuadas com valores em uma única linha não exigem abstenção.

O verificador atual só interpreta números brasileiros. Os quatro casos em formato americano preservam os valores documentais corretos no gabarito e são marcados com `evidence_supported=false`; a avaliação os inclui normalmente e contabiliza suas rejeições. USD/EUR não são convertidos e continuam inelegíveis nas regras de comparação. Não há OCR.

Este é um conjunto sintético de desenvolvimento, pequeno e sem separação entre treino e teste. Resultados nele não estimam desempenho em propostas reais nem garantem resistência geral a ataques.
