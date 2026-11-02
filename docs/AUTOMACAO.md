# Automação de recebimento com n8n

O arquivo [cotera-upload.n8n.json](../workflows/cotera-upload.n8n.json) conecta três nós:

**Receber PDF → Extrair e registrar no Cotera → Responder ao remetente**

A automação recebe o documento, encaminha para a API e devolve seu JSON e código HTTP. Não aprova propostas ou executa compras. A deduplicação, os limites e as conferências permanecem na API.

## Preparar

1. Com o ambiente do [Compose](../compose.yaml) ativo, abra `http://127.0.0.1:5678` e conclua a configuração inicial da sua instância n8n.
2. Importe o JSON como workflow.
3. O nó HTTP usa `http://cotera-api:8005`, nome do serviço na rede do Compose. Se o n8n estiver em outra instalação, ajuste a URL para o endereço da sua API.
4. Se `COTERA_API_KEY` estiver configurada, use uma credencial **Header Auth** no nó HTTP: nome `X-Cotera-Key`, valor igual à chave do servidor. O arquivo exportado não contém credenciais.
5. No nó **Receber PDF**, selecione **Listen for test event** e use a URL de teste mostrada pela sua instância.

O Cotera precisa ter uma cesta criada. Seu identificador completo está na resposta de `POST /requests` ou na listagem da API. O workflow recebe esse identificador em `request_id`.

## Enviar o PDF

No PowerShell, substitua o identificador e use a URL de teste exibida no n8n:

```powershell
curl.exe -X POST "http://127.0.0.1:5678/webhook-test/cotera-proposal?request_id=IDENTIFICADOR_DA_COTACAO" `
  -H "Content-Type: application/pdf" `
  -H "Content-Disposition: attachment; filename=aurora.pdf" `
  --data-binary "@data/proposals/aurora.pdf"
```

O envio é **binário bruto**, não multipart para o webhook. O cabeçalho `Content-Disposition` preserva o nome com extensão PDF. O Webhook produz o binário `data`; o nó HTTP o encaminha como o campo multipart `file` esperado pela API.

O modo padrão é `local`, compatível com o modelo Cotera. Para IA, configure as variáveis no servidor da API e acrescente `&mode=ai&approve_external_processing=true` à URL. Esse parâmetro representa a autorização explícita do chamador para enviar o texto ao provedor.

Após importar e testar na sua instância, publique/ative o workflow conforme a interface do n8n e use sua URL de produção, que troca `/webhook-test/` por `/webhook/`.

## Resultados esperados

| Resposta | Significado |
|---|---|
| `200`, `created: true` | Documento adicionado |
| `200`, `created: false` | Mesmos bytes já presentes na cotação |
| `403` | Falta de consentimento no modo com IA |
| `404` | Cotação não encontrada |
| `422` | Documento, modo ou valores inválidos |
| `502` | Falha do provedor ou extração sem evidência válida |

Erros de conexão do próprio n8n são falhas da execução, não respostas de validação do Cotera. O timeout do nó HTTP é 45 segundos; a chamada de extração tem timeout de 30 segundos e não faz repetição automática.

O fluxo foi entregue desativado. Não foi executado nesta validação local porque não há Docker/n8n instalado. A API que recebe o upload foi validada com PDF real pelos testes e por uma chamada HTTP local.

Referências: [Webhook do n8n](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.webhook) e [HTTP Request](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.httprequest).

[Voltar ao README](../README.md)
