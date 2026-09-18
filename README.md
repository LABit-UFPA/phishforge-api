# PhishForge

PhishForge é uma ferramenta educacional que gera exemplos de e-mails de phishing utilizando Inteligência Artificial. O objetivo é conscientizar e treinar usuários sobre técnicas de phishing, ajudando na prevenção contra ataques cibernéticos.

## Tecnologias Utilizadas

- **LangChain** - Para a geração de e-mails de phishing com IA.
- **Qdrant** - Base vetorial utilizada para armazenamento e busca semântica.
- **FastAPI** - Framework para exposição da API.
- **Poetry** - Gerenciador de dependências do projeto.
- **Docker Compose** - Orquestração de Postgres, Qdrant, migrations, API e frontend.

## Instalação e Configuração

1. Clone este repositório:

   ```bash
   git clone https://github.com/LABit-UFPA/phishforge-api.git
   cd phishforge-api
   ```

2. Configure as variáveis de ambiente:

   ```bash
   cp .env.example .env
   ```

   Preencha `OPENAI_API_KEY` no `.env`. É a única variável obrigatória —
   as demais têm default adequado para desenvolvimento local, e o
   `.env` é ignorado pelo git.

   > Nunca coloque a chave em `app/core/config.py`. Os defaults ali são
   > para o código funcionar sem `.env`; uma chave escrita no arquivo vai
   > para o repositório no próximo commit.

3. Suba a infraestrutura com Docker Compose:

   ```bash
   docker compose up -d
   ```

   Isso sobe Postgres, Qdrant, as migrations (flyway), a API e o frontend
   de curadoria. A porta do Postgres não é publicada no host, de propósito:
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

## Uso

A API disponibiliza endpoints para gerar e-mails de phishing educacionais. Para testar, acesse:

- **Swagger UI**: `http://localhost:8000/docs`
- **Redoc**: `http://localhost:8000/redoc`
