# Guia: gerar exemplos de phishing para análise

Este guia é para quem precisa **gerar exemplos de e-mails de phishing com o
PhishForge e exportá-los para análise** (por exemplo, para o artigo), sem
precisar configurar banco de dados, base vetorial nem nada do código.

Você vai rodar **um comando** e o Docker sobe tudo: o site de geração, a API,
o banco de dados (Postgres) e a base de artigos científicos (Qdrant), que
**já vem indexada**. A única coisa que você precisa fornecer é uma chave da
OpenAI.

---

## O que você precisa

Funciona em **Windows 10/11, macOS (Intel ou Apple Silicon) e Linux**
(x86-64 ou ARM64). Os comandos abaixo são os mesmos nos três sistemas,
exceto quando indicado. No Windows, use o PowerShell.

- **Docker**
  - Windows ou macOS: [Docker Desktop](https://www.docker.com/products/docker-desktop/).
    No Windows, aceite a opção de usar o WSL 2 durante a instalação.
  - Linux: Docker Engine com o plugin `docker compose`.
  - Abra o Docker Desktop e espere ele indicar que está rodando antes de continuar.
- **Git**, para baixar o código.
- **Uma chave da OpenAI** (começa com `sk-`), passada pelo orientador.
  **Não compartilhe essa chave nem a coloque em nenhum arquivo do git.**
- Uns **8 GB livres em disco** e internet. A primeira subida baixa cerca de 5 GB.
- As portas **3000, 8000, 6333 e 6334** livres no seu computador.

---

## 1. Baixar o projeto

Os dois repositórios precisam ficar **lado a lado, na mesma pasta**:

```bash
mkdir phishforge
cd phishforge
git clone https://github.com/LABit-UFPA/phishforge-api.git
git clone https://github.com/LABit-UFPA/phishforge-frontend.git
cd phishforge-api
```

O resultado deve ser:

```
phishforge/
├── phishforge-api/        ← os comandos deste guia rodam aqui
└── phishforge-frontend/
```

## 2. Colocar a chave da OpenAI

Crie o arquivo `.env` a partir do modelo:

```bash
# Linux / macOS
cp .env.example .env

# Windows (PowerShell)
copy .env.example .env
```

Abra o `.env` num editor de texto (no Windows, o Bloco de Notas serve),
preencha a linha abaixo com a sua chave e salve:

```
OPENAI_API_KEY=sk-...sua-chave...
```

Para os lotes do protocolo de geração, preencha também o modelo com o
**snapshot** definido com o orientador (não o alias `gpt-4o-mini`, que pode
mudar de modelo sem aviso):

```
MODEL_NAME_LLM=gpt-4o-mini-2024-07-18
```

Deixe todo o resto como está. Se mudar o `.env` com tudo já rodando, aplique
com `docker compose up -d` (passo 3). O modelo usado em cada lote fica
registrado no próprio lote (`run_metadata`) e no `lotes.csv` da exportação.

## 3. Subir tudo

Ainda na pasta `phishforge-api`:

```bash
docker compose up -d --build
```

- **A primeira vez demora** (de 10 a 20 minutos, dependendo da internet),
  porque o Docker baixa e monta as imagens. Das próximas vezes leva segundos.
- O Docker sobe, nesta ordem: banco de dados → base de artigos (restaurada
  automaticamente) → tabelas do banco → API → site.

Para saber se terminou:

```bash
docker compose ps
```

Os serviços `phishforge-api`, `phishforge-frontend`, `phishforge-postgresql` e
`phishforge-qdrant` devem aparecer como `running`/`Up`. Os serviços
`phishforge-flyway` e `phishforge-qdrant-seed` rodam uma vez e terminam. É
normal eles aparecerem como `exited (0)`.

## 4. Gerar exemplos

Abra **http://localhost:3000** no navegador. A aba **Gerador** é a tela
inicial.

O campo **Contexto** é obrigatório: descreva o cenário do e-mail. Por
exemplo: *"e-mail bancário pedindo confirmação de cadastro"*, *"aviso de
matrícula da UFPA"*, *"entrega de encomenda pendente"*. A geração sempre
produz **e-mail**.

### Um exemplo por vez (modo **Único**)

1. Em **Modo de geração**, escolha **Único**.
2. Escolha a **Dificuldade**: Fácil, Médio ou Difícil.
3. Deixe marcado **"Gerar phishing"**. Desmarcado, o sistema gera um e-mail
   legítimo, que não é o objetivo aqui.
4. Preencha o **Contexto** e clique em **Gerar**.

Cada exemplo leva de alguns segundos a cerca de meio minuto. O **primeiro**
pode demorar mais, porque a API baixa um modelo auxiliar na primeira vez.

### Vários exemplos de uma vez (modo **Lote**)

1. Em **Modo de geração**, escolha **Lote**.
2. Em **Dificuldades**, marque os níveis desejados. O total é dividido
   igualmente entre eles. Por exemplo, 30 itens com os três níveis dão 10 de cada.
3. Defina o **Total de itens**, de 1 a 100.
4. Preencha o **Contexto** e clique em **Gerar**.

O lote gera **apenas phishing** e roda em segundo plano. A barra mostra o
andamento ("12/30 gerados"). Você pode recarregar a página que o
acompanhamento continua. Exemplos muito parecidos com outros do mesmo lote
são descartados automaticamente. Por isso o total gerado pode ficar um pouco
abaixo do pedido.

Cada exemplo recebe uma **ficha sorteada** pelo sistema: nome do
destinatário, quem assina, detalhe do pretexto, ação pedida, tom, estrutura,
abertura e as pistas de phishing que o e-mail deve conter. É o que evita que
os exemplos de um mesmo contexto saiam como cópias uns dos outros. A ficha
fica guardada junto do exemplo.

### Vários lotes da mesma célula do protocolo (Swagger)

O site não expõe estas duas opções; use o Swagger em
**http://localhost:8000/docs**, rota `POST /api/v1/generate/batch` (preencha o
campo `x-api-key` com `phishforge-local`, ou com o `API_KEY` do seu `.env`):

- **`dedup_job_ids`**: lista de `job_id` de lotes anteriores **da mesma
  célula**. Os exemplos desses lotes entram na checagem de repetição, então o
  2º, 3º e 4º lote de uma célula não repetem exemplos dos anteriores.
  **Não inclua lotes-piloto.**
- **`seed`**: semente do sorteio das fichas. Com a mesma semente, o lote
  sorteia as mesmas fichas. Se omitida, o sistema sorteia uma e a registra.

Exemplo de corpo para o 2º lote de uma célula:

```json
{
  "context": "Estudante de graduação de uma universidade pública brasileira recebe ...",
  "difficulties": ["medio"],
  "total": 50,
  "dedup_job_ids": ["<job_id do 1º lote desta célula>"]
}
```

O `GET /api/v1/generate/batch/{job_id}` mostra, além dos exemplos, o
`attempt_log` (cada tentativa, inclusive as descartadas, com a similaridade
com o exemplo mais parecido) e o `run_metadata` (modelo, temperatura,
semente, limiar e o contexto que o gerador recebeu).

> **Dica para a análise:** use um contexto por lote e anote quais contextos
> você usou. A exportação (passo 6) já traz, para cada exemplo gerado em
> lote, o contexto que o originou. Exemplos gerados no modo Único não
> guardam o contexto.

Há um limite de **20 gerações por minuto**. Um lote conta como uma só
geração, então esse limite só aparece se você clicar em **Gerar** muitas
vezes seguidas no modo Único.

## 5. Conferir os exemplos

A aba **Exemplos** lista tudo o que já foi gerado, com filtros por nível e
categoria e busca por texto. Clique no ícone de olho para ver um exemplo
completo, com a explicação das técnicas usadas e as pistas de phishing.

## 6. Exportar para análise (CSV)

Na pasta `phishforge-api`:

```bash
docker compose run --rm phishforge-export
```

Os arquivos aparecem em `phishforge-api/exports/`. Eles abrem no Excel,
LibreOffice, Google Sheets, pandas ou R. Use a codificação UTF-8 ao importar.

**`exemplos.csv`**: um exemplo por linha.

| Coluna | O que é |
|---|---|
| `id` | identificador do exemplo |
| `created_at` | quando foi gerado |
| `is_malicious` | `t` = phishing, `f` = legítimo |
| `nivel` | dificuldade **pedida** na geração (facil, medio, dificil) |
| `difficulty_estimated` | dificuldade **estimada** pelo NIST Phish Scale a partir do próprio e-mail |
| `phish_scale_cue_count` | quantidade de pistas de phishing identificadas (Phish Scale) |
| `phish_scale_premise_alignment` | quanto a premissa do e-mail se alinha ao público (baixo, medio, alto) |
| `categoria` | categoria do golpe (ex.: financeiro) |
| `remetente`, `receptor`, `assunto`, `conteudo` | o e-mail em si |
| `explicacao` | explicação das técnicas de phishing usadas |
| `links` | links do e-mail (texto exibido e destino real) |
| `pistas` | códigos das pistas anotadas pelo LLM, separados por `;` |
| `pistas_alvo` | códigos das pistas que a ficha mandou incluir, separados por `;` (vazio em exemplos anteriores à ficha) |
| `ficha` | a ficha sorteada para o exemplo (JSON) |
| `validacao` | o que a validação automática corrigiu (JSON): evidências que não são trecho literal do texto, pistas removidas, regenerações por marcador como `[Nome]` e pistas-alvo que o LLM não anotou |
| `lote_id`, `contexto_lote` | o lote e o contexto que geraram o exemplo (vazios no modo Único) |

**`pistas.csv`**: uma pista por linha (um e-mail pode ter várias).

| Coluna | O que é |
|---|---|
| `email_id` | o `id` do exemplo em `exemplos.csv` |
| `pista`, `pista_rotulo`, `pista_categoria` | código, nome e tipo (técnica ou psicológica) da pista |
| `evidencia` | o trecho do e-mail que evidencia a pista |
| `span_start`, `span_end` | posição desse trecho no `conteudo`, calculada pelo sistema. Vazios só quando a evidência não é um trecho literal do texto |

**`lotes.csv`**: um lote por linha, com status, totais e os parâmetros com
que rodou (modelo, temperatura, semente, limiar de repetição, lotes usados na
checagem).

**`tentativas.csv`**: uma tentativa de geração por linha, inclusive as
descartadas, com a similaridade com o exemplo mais parecido já aceito e o
resultado (`aceito`, `repetido`, `descartado` ou `falha`). É daqui que sai a
taxa de descarte e a distribuição de similaridade de cada lote.

Rode o comando de novo sempre que quiser um retrato atualizado. Ele
sobrescreve os arquivos.

## Parar e retomar

```bash
docker compose stop      # para tudo; os exemplos continuam guardados
docker compose up -d     # volta de onde parou
```

> ⚠️ **Não use `docker compose down -v`** a menos que queira **apagar todos os
> exemplos gerados**: o `-v` remove o banco de dados. Exporte antes.

---

## Problemas comuns

| Sintoma | Causa provável e solução |
|---|---|
| `Cannot connect to the Docker daemon` / `docker: command not found` | O Docker Desktop não está aberto. Abra e espere ele iniciar. |
| `port is already allocated` (3000, 8000, 6333 ou 6334) | Outro programa usa a porta. Feche-o, ou rode `docker ps` para ver se há outro container ocupando a porta. |
| `localhost:3000` não abre | A API ainda está subindo. Aguarde um minuto e confira com `docker compose ps`. |
| Erro 500 ao gerar, com mensagem `Error building context` | A chave da OpenAI está errada, vazia ou sem crédito. Corrija o `.env` e rode `docker compose up -d` de novo. |
| Erro 429 (*Too Many Requests*) | Limite de 20 gerações por minuto. Espere um minuto, ou use o modo Lote. |
| Lote fica "Gerando exemplos…" para sempre | A API foi reiniciada no meio do lote. Gere o lote de novo. Os itens já gerados continuam salvos. |

Se nada disso resolver, mande ao orientador a saída de:

```bash
docker compose ps
docker compose logs --tail 100 phishforge-api
```

---

## Para o texto do artigo: como cada exemplo é gerado

1. O contexto digitado é **normalizado** por um LLM, que produz uma consulta
   de busca e um contexto de geração.
2. **HyDE**: o LLM escreve uma resposta hipotética, usada para melhorar a busca.
3. **Busca** dos 20 trechos mais próximos na base de artigos. A base reúne
   15 documentos sobre phishing, divididos em 800 trechos com embeddings
   `text-embedding-3-small`.
4. **Reordenação** desses trechos por um *cross-encoder*
   (`ms-marco-MiniLM-L-6-v2`).
5. **Fusão**: os 3 melhores trechos são resumidos num contexto acadêmico.
6. **Ficha**: o sistema sorteia, para o exemplo, destinatário, quem assina,
   detalhe do pretexto, ação, tom, estrutura, abertura e as pistas-alvo do
   nível. O sorteio é balanceado: dentro de um lote, cada valor (e cada par de
   pistas, no nível médio) aparece com frequência parecida.
7. **Geração** do e-mail pelo LLM (snapshot fixado em `MODEL_NAME_LLM`), na
   dificuldade pedida e seguindo a ficha, com explicação, pistas anotadas e
   estimativa pelo NIST Phish Scale.
8. **Validação automática**: posição de cada pista calculada a partir do
   trecho citado; `generic_greeting` removida quando a saudação usa o nome do
   destinatário; exemplo gerado de novo se vier com marcador como `[Nome]`.
9. **Checagem de repetição**: similaridade de cosseno (embeddings
   `text-embedding-3-small`) com os exemplos já aceitos no lote e nos lotes
   indicados em `dedup_job_ids`. Acima de 0,95, o exemplo é gerado de novo com
   outra ficha, até 2 vezes; depois disso, é descartado.

No lote, os passos 1 a 5 rodam uma vez e os passos 6 a 9 rodam uma vez por
exemplo.
