# Cotera — do orçamento à escolha documentada

## Problema

Comparar orçamentos não é apenas comparar o número escrito como total. Uma proposta pode usar outra quantidade, omitir frete ou trazer uma soma incorreta. Quando as condições ficam espalhadas em documentos, a origem da escolha também se perde.

## Solução

A cesta define o que será comprado antes de receber os documentos. O Cotera extrai as propostas, mostra suas fontes e aplica as mesmas regras a todos os fornecedores. A pessoa responsável escolhe entre propostas elegíveis e registra sua justificativa.

A extração com IA transforma texto em campos; o cálculo continua determinístico. Essa separação permite apontar tanto um campo sem evidência quanto uma divergência aritmética.

## Cenário demonstrativo

Três fornecedores fictícios cotam a mesma cesta de materiais. Prumo oferece o menor custo elegível, Aurora declara prazo menor e Vértice apresenta um total inconsistente. O projeto evidencia a diferença entre ordenar valores e comparar propostas equivalentes.

O prazo máximo é opcional e pertence à cesta. Se a necessidade exigir até seis dias, uma proposta de oito dias fica pendente mesmo que seja a mais barata. Não existe uma classificação de “melhor fornecedor” baseada apenas no nome ou em uma avaliação subjetiva do LLM.

[Tela de documentos e evidências](images/documentos.jpg) · [Tela do histórico de decisões](images/decisao.jpg)

## Evidências técnicas

O [relatório de avaliação](../reports/evaluation.json) contém oito casos sintéticos com resultado esperado e observado. Os [testes](../tests/) exercitam documentos reais do exemplo, contratos, fonte dos campos, concorrência, API e navegação.

As propostas são deduplicadas por hash dos bytes dentro da cotação. As decisões guardam o valor aprovado e a versão do conjunto; uma tentativa baseada em uma fotografia anterior é recusada.

## Limites

O projeto não tem uso em empresa ou economia de horas comprovada. A extração local é específica do modelo fornecido; a integração com LLM foi verificada por contrato com cliente simulado, sem avaliação de precisão em propostas de fornecedores reais. PostgreSQL e n8n têm configuração e integração fornecidas, com a execução local desses serviços ainda não validada.

[Voltar ao README](../README.md)
