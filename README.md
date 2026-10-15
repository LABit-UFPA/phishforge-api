# PhishForge

PhishForge é uma ferramenta educacional que gera exemplos de e-mails de phishing utilizando Inteligência Artificial. O objetivo é conscientizar e treinar usuários sobre técnicas de phishing, ajudando na prevenção contra ataques cibernéticos.

## Tecnologias Utilizadas

- **LangChain** - Para a geração de e-mails de phishing com IA.
- **Qdrant** - Base vetorial utilizada para armazenamento e busca semântica.
- **FastAPI** - Framework para exposição da API.
- **Poetry** - Gerenciador de dependências do projeto.
- **Docker Compose** - Orquestração de Postgres, Qdrant, migrations, API e frontend.

> **Só quer gerar exemplos (ex.: para análise no artigo)?** Siga o
> [guia de geração de exemplos](docs/guia_geracao_exemplos.md): um
> `docker compose up` sobe tudo, com a base de artigos já indexada.

## Instalação e Configuração

1. Clone este repositório e o do frontend, lado a lado na mesma pasta
   (o compose constrói o frontend a partir de `../phishforge-frontend`):

   ```bash
   git clone https://github.com/LABit-UFPA/phishforge-api.git
   git clone https://github.com/LABit-UFPA/phishforge-frontend.git
   cd phishforge-api
   ```

2. Configure as variáveis de ambiente:

   ```bash
   cp .env.example .env
   ```

   Preencha `OPENAI_API_KEY` no `.env`. Pelo compose, é a única variável
   obrigatória — as demais têm default adequado para desenvolvimento
   local (inclusive `API_KEY`, que vazia vira `phishforge-local`; por isso
   API e frontend só escutam em `127.0.0.1`), e o `.env` é ignorado pelo
   git.

   > Nunca coloque a chave em `app/core/config.py`. Os defaults ali são
   > para o código funcionar sem `.env`; uma chave escrita no arquivo vai
   > para o repositório no próximo commit.

3. Suba a infraestrutura com Docker Compose:

   ```bash
   docker compose up -d --build
   ```

   Isso sobe Postgres, Qdrant, as migrations (flyway), a API e o frontend
   de curadoria (`http://localhost:3000`). Na primeira subida, o serviço
   `phishforge-qdrant-seed` restaura a coleção `phishing_articles` (os
   artigos de `data/articles` já indexados) a partir de
   `qdrant/phishing_articles.snapshot` — não é preciso rodar a ingestão.
   Ele só restaura se a coleção não existir, então nunca sobrescreve uma
   base reindexada. A porta do Postgres não é publicada no host, de propósito:
   o `phishing-quest-api` também usa 5432 e os dois stacks precisam subir
   juntos. Para inspecionar o banco:

   ```bash
   docker exec -it phishforge-postgresql psql -U phishforge -d phishforge
   ```

4. Para rodar a API fora do compose, instale as dependências e suba o
   servidor:

   ```bash
   poetry install
   poetry run uvicorn main:app --reload
   ```

   Nesse modo, Postgres e Qdrant precisam estar acessíveis nos endereços
   do `.env` (por padrão, `localhost`).

### Atualizar a base vetorial (snapshot)

O snapshot versionado em `qdrant/phishing_articles.snapshot` é o que
quem sobe o compose do zero recebe. Ao mudar os artigos de
`data/articles` ou o chunking, reindexe e gere um snapshot novo:

```bash
poetry run python script/run_ingestion.py   # recria a coleção (usa a OpenAI)

NOME=$(curl -s -X POST "http://localhost:6333/collections/phishing_articles/snapshots?wait=true" \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['result']['name'])")
curl -sf -o qdrant/phishing_articles.snapshot \
  "http://localhost:6333/collections/phishing_articles/snapshots/$NOME"
curl -s -X DELETE "http://localhost:6333/collections/phishing_articles/snapshots/$NOME"
```

O snapshot só restaura em Qdrant da mesma versão ou mais nova que a que
o gerou (hoje `v1.18.0`, fixada no compose).

### Exportar os exemplos gerados

```bash
docker compose run --rm phishforge-export
```

Grava `exports/exemplos.csv` (um exemplo de e-mail por linha, com pistas
e o contexto do lote que o gerou) e `exports/pistas.csv` (uma pista
anotada pelo LLM por linha). A consulta fica em
`script/exportar_exemplos.sql`.

## Testes

A suite fica em `tests/`, separada em duas camadas:

- `tests/unit/` — contrato dos endpoints com o pipeline inteiro (LLM,
  cross-encoder, base vetorial) substituido por fakes (`tests/fakes.py`).
  Nao faz chamada de rede nem precisa de banco.
- `tests/integration/` — usa Postgres de verdade, com o schema aplicado
  pelas MESMAS migrations do flyway usadas em producao.

A porta do Postgres nao e publicada por padrao (ver seção de
instalação), entao os testes de integração fora do compose
precisam de um `docker-compose.override.yml` local (nunca
versionado) publicando-a:

```yaml
services:
  phishforge-postgresql:
    ports:
      - "5432:5432"
```

```bash
# so os unitarios, sem infra nenhuma
poetry run pytest tests/unit -v

# integracao: com o override acima aplicado
docker compose up -d phishforge-postgresql phishforge-flyway
poetry run pytest tests/integration -v
```

Lint (`ruff`), escopo restrito a `app/` e `tests/`:

```bash
poetry run ruff check app tests
```

O CI (`.github/workflows/pr_ci.yml`) roda os tres em todo PR e todo push
para `main`, cada um em um job separado.

## Uso

A API disponibiliza endpoints para gerar e-mails de phishing educacionais. Para testar, acesse:

- **Swagger UI**: `http://localhost:8000/docs`
- **Redoc**: `http://localhost:8000/redoc`
