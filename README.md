# ◒ Cotera

**Cotações comparáveis. Decisões que deixam rastro.**

🔗 Demo online: (link em breve)

Receba propostas de fornecedores em PDF, transforme os documentos em dados e compare a mesma cesta de produtos. O Cotera confere quantidades, unidades, frete, desconto, prazo e total antes de liberar o registro da escolha.

## Como funciona

```mermaid
flowchart LR
    A["PDF / TXT"] --> B["Texto numerado"]
    B --> C["Parser local"]
    B --> D["LLM opcional"]
    C --> E["Validação Pydantic + evidência por linha"]
    D --> E
    E --> F["Regras e recálculo com Decimal"]
    F --> G["Comparação"]
    G --> H["Decisão humana com histórico"]
```

## Destaques técnicos

- Parser local como padrão: demonstração e conferências funcionam sem chave de API.
- LLM opcional, exibido somente com `OPENAI_API_KEY` no ambiente ou em `st.secrets`, com autorização antes de enviar o texto.
- Contratos Pydantic e conferência literal dos valores nas linhas citadas, com o texto disponível para revisão.
- Recálculo com `Decimal` e `ROUND_HALF_UP`; propostas com pendências ficam fora da escolha e do menor custo elegível.
- Deduplicação pelo hash do arquivo, transações e decisões vinculadas à versão da cotação, preservando o histórico.
- SQLite com fallback para diretório temporário e adaptador PostgreSQL; exportação em HTML, CSV e JSON.
- API FastAPI, workflow n8n importável e CI com Python 3.12 e 3.14 e serviço PostgreSQL.

A qualidade da extração com LLM ainda não foi medida com um modelo real. A avaliação reproduzível usa o parser local e casos sintéticos; os testes de IA usam um cliente simulado.

## Interface

![Mesa de compras do Cotera com três propostas lado a lado](docs/images/comparacao.jpg)

| Documentos e evidências | Decisão e histórico |
|---|---|
| ![Documento e linhas de origem na interface](docs/images/documentos.jpg) | ![Registro da decisão humana](docs/images/decisao.jpg) |

**Stack:** Python 3.12+ · Streamlit · Pydantic · pypdf · Decimal · SQLite / PostgreSQL (psycopg) · FastAPI / Uvicorn · SDK OpenAI opcional · pytest · Docker Compose · n8n.

[Estudo de caso](docs/ESTUDO_DE_CASO.md) · [Arquitetura](docs/ARQUITETURA.md) · [Automação com n8n](docs/AUTOMACAO.md) · [Avaliação reproduzível](reports/evaluation.json)

## Uma compra, três momentos

1. **Comparar:** veja a cesta, as propostas, os preços unitários e as pendências. O menor custo é destacado apenas entre propostas elegíveis.
2. **Documentos:** adicione PDF/TXT e confira cada campo com a linha de origem.
3. **Decisões:** consulte quem registrou a escolha, a justificativa e a versão comparada. Exporte HTML, CSV ou JSON.

Em **Minhas cotações**, crie uma cesta própria com códigos, descrições, quantidades, unidades e prazo máximo opcional. Cada cotação aceita até dez propostas. A demonstração usa um banco separado.

O registro da escolha não envia pedidos, contrata fornecedores nem realiza pagamentos. Uma nova escolha acrescenta um evento; o histórico anterior é preservado.

## Demonstração verificável

A cesta contém vinte resmas de papel, cinquenta canetas e dez organizadores. Todos os fornecedores, referências e condições são fictícios.

| Fornecedor | Total calculado | Prazo declarado | Conferência |
|---|---:|---:|---|
| Aurora Suprimentos | R$ 1.405,00 | 5 dias | Elegível |
| Prumo Distribuidora | R$ 1.320,00 | 8 dias | Menor custo elegível |
| Vértice Comercial | R$ 1.350,00 | 4 dias | Pendente: o documento declara R$ 1.290,00 |

A diferença entre Aurora e Prumo é uma comparação de valores fictícios, não uma economia obtida por uma empresa. A escolha considera a justificativa da pessoa responsável; menor custo não é sinônimo de melhor fornecedor em todos os critérios.

Os exemplos estão em [data/proposals](data/proposals). O [gerador dos documentos](scripts/create_samples.py) reproduz os PDFs e TXTs a partir de valores explícitos.

## Como rodar localmente

### Instalação e interface

Na raiz do projeto, no Windows com Python 3.12:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py --server.port 8505 --server.showEmailPrompt false
```

Abra `http://127.0.0.1:8505`. A demonstração funciona sem chave de API, PostgreSQL ou Docker. Os PDFs fictícios acompanham o projeto; a leitura do modelo Cotera e todas as conferências são locais.

Em Linux/macOS:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m streamlit run app.py --server.port 8505 --server.showEmailPrompt false
```

Com [uv](https://docs.astral.sh/uv/), a versão e as dependências também podem ser selecionadas pelo projeto:

```bash
uv run --python 3.12 streamlit run app.py --server.port 8505
```

### Streamlit Community Cloud

1. Selecione o repositório `GustavoCurio/Cotera`, a branch desejada e o entrypoint **`app.py`**.
2. Em **Advanced settings**, escolha **Python 3.12**.
3. Publique sem configurar chave: a demonstração e o parser local funcionam assim. Use **Carregar exemplo** para abrir a cesta e as três propostas fictícias, inclusive ao sair de **Minhas cotações**.

O [`requirements.txt`](requirements.txt) da raiz contém as dependências de execução e é o manifesto instalado pelo Cloud; `uv.lock` não é versionado. O [`pyproject.toml`](pyproject.toml) declara `requires-python = ">=3.12"` e lê as mesmas dependências. Veja a [documentação de dependências do Community Cloud](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/app-dependencies).

Para habilitar IA, cadastre `OPENAI_API_KEY` nos **Secrets** do aplicativo ou no ambiente. Você também pode definir `OPENAI_MODEL`; se estiver ausente, a interface permite informar o modelo antes da extração. Sem chave, a opção de IA não aparece. Nunca versione credenciais: `.env` e `.streamlit/secrets.toml` estão no `.gitignore`. A [documentação de Secrets do Community Cloud](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management) explica a configuração no painel.

### O que está implementado

| Recurso | Comportamento |
|---|---|
| Cesta de referência | Códigos únicos, quantidades e unidades validadas |
| Leitura documental | PDF textual e TXT UTF-8, com linhas numeradas |
| Extração local | Parser do modelo rotulado incluído no projeto |
| Extração com IA | Texto numerado → JSON estruturado → validação de evidências |
| Conferência | Cesta, completude, moeda, prazo e reconciliação do total |
| Comparação | Mesmo conjunto de itens; menor custo entre elegíveis; empates preservados |
| Decisão humana | Responsável, justificativa, valor e versão do conjunto |
| Concorrência | Decisão desatualizada é recusada, sem sobrescrever o histórico |
| Idempotência | Os mesmos bytes na mesma cotação não geram uma nova proposta |
| Persistência | SQLite local; adaptador PostgreSQL pelo mesmo contrato |
| Integração | API FastAPI e workflow n8n importável |
| Exportação | HTML independente, CSV para planilhas e JSON com evidências |

### Como os valores são conferidos

O total é calculado por **soma das linhas arredondadas para centavos + frete − desconto**, usando `Decimal` e `ROUND_HALF_UP` em cada linha. Nenhum cálculo financeiro é delegado ao LLM.

Para ser elegível, a proposta precisa:

- Informar fornecedor, referência, moeda, prazo, frete, desconto e total declarado.
- Usar BRL e conter exatamente os códigos, quantidades e unidades da cesta.
- Não conter códigos repetidos ou itens adicionais.
- Ter total declarado igual ao calculado, sem resultado negativo.
- Atender ao prazo máximo, quando definido na cesta.

Ausência permanece ausente. Frete ou desconto em branco não vira zero. Não há conversão de moeda, equivalência entre embalagens/unidades ou cálculo de impostos adicionais. O prazo usa o número de dias declarado; não há conversão de datas ou de dias úteis.

### Documentos e evidências

| Limite | Valor |
|---|---:|
| Arquivo | Até 2 MiB |
| PDF | Até cinco páginas, sem senha e com texto selecionável |
| Texto | Até 25 mil caracteres e mil linhas |
| Cesta pela API | Até vinte itens; formulário visual: até dez |
| Propostas por cotação | Até dez |

O parser local aceita os rótulos e a tabela do [modelo TXT](data/proposals/aurora.txt). Os números do documento seguem o formato brasileiro, como `1.405,00`; os dados estruturados usam strings decimais, como `"1405.00"`.

Cada campo extraído precisa corresponder literalmente à linha citada. Números são comparados após leitura no formato brasileiro; `R$` também é evidência explícita de BRL. Essa verificação não comprova que o modelo associou cada número à coluna correta. O texto original permanece disponível para conferência.

Os PDFs não são guardados no banco. O nome, o hash, o texto extraído e os dados estruturados são persistidos junto da proposta. O JSON exportado inclui esse texto. Não há OCR nesta versão.

### Extração com IA

Configure as variáveis no ambiente do processo antes de iniciar o aplicativo (ou nos segredos do Streamlit, para a interface):

```powershell
$env:OPENAI_API_KEY = "sua-chave"
$env:OPENAI_MODEL = "modelo-compativel-com-saida-estruturada"
.\.venv\Scripts\python.exe -m streamlit run app.py --server.port 8505 --server.showEmailPrompt false
```

O parser local é o padrão. A opção **Extração com IA** só aparece na interface quando há `OPENAI_API_KEY` no ambiente ou em `st.secrets`. `OPENAI_MODEL` pode ser configurado nesses mesmos lugares ou informado na interface. A extração exige autorização na interface ou `approve_external_processing=true` na API. Envia somente o texto numerado e os códigos da cesta à OpenAI. Pode consumir créditos da API; não usa a assinatura do ChatGPT.

A integração usa a Responses API com [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs), esquema estrito, `store=False`, tempo limite e validação posterior com Pydantic. Texto documental é tratado como dado não confiável. O modelo não recebe ferramentas de compra nem permissão para registrar decisões.

O modo com IA admite outros layouts apenas quando consegue associar os valores a linhas de origem. Itens distribuídos em múltiplas linhas podem ficar incompletos e pendentes. A avaliação de referência abaixo mede o parser local e as regras; o contrato da integração com IA é testado com cliente simulado, sem medição de qualidade de um modelo real.

### API e automação

```powershell
.\.venv\Scripts\python.exe -m uvicorn cotera.api:app --host 127.0.0.1 --port 8005
```

Documentação interativa: `http://127.0.0.1:8005/docs`.

| Método e rota | Uso |
|---|---|
| `GET /health` | Disponibilidade e versão |
| `GET /requests` | Listar cestas |
| `POST /requests` | Criar cesta |
| `GET /requests/{id}` | Comparação, documentos e decisões |
| `POST /requests/{id}/proposals` | Upload multipart de PDF/TXT |
| `POST /requests/{id}/decisions` | Registrar escolha com `expected_version` |
| `GET /requests/{id}/report` | Relatório HTML |

Quando `COTERA_API_KEY` está definida, as rotas exigem o cabeçalho `X-Cotera-Key`. O aplicativo local não possui contas ou separação de dados por usuário; é uma mesa de compras de uma única instalação. Os comandos e o Compose publicados usam acesso local.

O [workflow n8n](workflows/cotera-upload.n8n.json) recebe PDF por webhook, chama a API e devolve o resultado. Veja [importação, chamada de exemplo e configuração de credenciais](docs/AUTOMACAO.md).

### PostgreSQL e Docker

Sem configuração, a aplicação usa `storage/cotera.sqlite3`; a demonstração usa `storage/demo.sqlite3`. Se o diretório ou o arquivo padrão não permitir gravação, os bancos são criados em `cotera/` dentro de `tempfile.gettempdir()`, com os mesmos nomes e separados entre si. Caminhos configurados explicitamente por `COTERA_DATABASE_URL` ou `COTERA_DEMO_HOME` são respeitados; erros nesses caminhos não são ocultados por um fallback. No Community Cloud, o armazenamento é efêmero e pode ser perdido em reinicializações; use as exportações para guardar a comparação. Para PostgreSQL, configure `COTERA_DATABASE_URL` com a URI e, opcionalmente, a senha separada em `COTERA_DB_PASSWORD`.

Com Docker e Docker Compose já instalados, copie `.env.example` para `.env`, defina `POSTGRES_PASSWORD` e execute:

```powershell
docker compose up --build -d
```

O Compose sobe PostgreSQL, interface, API e n8n. Endereços locais: interface `8505`, API `8005`, n8n `5678` e PostgreSQL `5433`. A interface e a API usam o mesmo banco PostgreSQL; a demonstração continua separada em SQLite. Pare instâncias nativas que estejam usando essas portas antes de subir o Compose.

O `.env` é lido pelo Docker Compose. Na execução Python nativa, as variáveis precisam estar no ambiente; o código não carrega esse arquivo automaticamente.

### Testes e avaliação

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m cotera evaluate
```

Na validação desta alteração, em **Python 3.12.16 e 3.14.10: 47 testes passaram e 1 foi pulado em cada versão**. O teste de PostgreSQL foi pulado por não haver servidor disponível; ele é habilitado por `COTERA_TEST_POSTGRES_URL`. O [workflow de CI](.github/workflows/tests.yml) configura um serviço PostgreSQL e executa a suíte e a avaliação nas duas versões de Python. A execução de PostgreSQL e n8n/Compose não foi verificada nesta máquina, onde Docker não está instalado.

Os testes locais cobrem PDF/TXT, limites, números ambíguos, dados ausentes, evidências inválidas, arredondamento, deduplicação, transações, decisões concorrentes, exportação, API e os fluxos da interface. Também verificam a oferta de IA por chave em ambiente/segredos, o modo local inicial, o botão de exemplo, o fallback do SQLite e a ausência da chave nos dados persistidos/exportados.

O [relatório de referência](reports/evaluation.json) registra **8/8 casos de conferência atendidos**: propostas completas, total incorreto, frete ausente, quantidade divergente, outra moeda, item repetido e item ausente. É um conjunto sintético de desenvolvimento; não demonstra precisão em documentos externos nem economia de horas em uma operação real.

Pelo terminal:

```powershell
.\.venv\Scripts\python.exe -m cotera extract data/proposals/aurora.pdf
.\.venv\Scripts\python.exe -m cotera demo
```

`demo` grava exemplos no banco configurado para a API/terminal. A demonstração visual usa seu próprio banco.

Com uv, execute a suíte completa e a avaliação:

```bash
uv run --python 3.12 --group dev pytest -q
uv run --python 3.14 --group dev pytest -q
uv run --python 3.12 python -m cotera evaluate
```

O servidor também foi iniciado em Python 3.12 por pelo menos 15 segundos com `streamlit run app.py --server.headless true`: `curl http://127.0.0.1:8505/_stcore/health` retornou **HTTP 200 / `ok`**, sem erros nos logs. Os fluxos da aplicação foram exercitados pelos testes de interface.

### Estrutura

| Caminho | Responsabilidade |
|---|---|
| `app.py` | Entrypoint Streamlit: mesa de compras, documentos, decisão e exportação |
| `pyproject.toml` / `requirements.txt` | Python mínimo, dependências e instalação no Cloud |
| `cotera/documents.py` | PDF/TXT, parser local e verificação de evidências |
| `cotera/extraction.py` | Contrato e integração de extração com IA |
| `cotera/comparison.py` | Cesta, cálculos e elegibilidade |
| `cotera/service.py` | Fluxo de inclusão e deduplicação anterior ao provedor |
| `cotera/store.py` | SQLite/PostgreSQL, transações e versões |
| `cotera/api.py` | Integração HTTP |
| `cotera/reports.py` | HTML, CSV e JSON |
| `cotera/evaluation.py` | Casos de referência reproduzíveis |
| `workflows/` | Automação n8n importável |

Projeto demonstrativo desenvolvido com assistência de IA. Os exemplos são fictícios; não há implantação em empresa, compras executadas ou resultados de produção declarados.
