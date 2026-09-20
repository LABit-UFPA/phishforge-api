# PhishForge API - Guia de Integração

Este documento descreve como integrar a PhishForge API em outros sistemas, focando nos endpoints de **geração de exemplos de phishing** e **avaliação das respostas dos usuários**.

## Sumário

1. [Visão Geral](#visão-geral)
2. [Autenticação](#autenticação)
3. [Endpoints Disponíveis](#endpoints-disponíveis)
   - [Geração de Phishing](#1-geração-de-phishing)
   - [Avaliação de Respostas](#2-avaliação-de-respostas-do-usuário)
   - [Listagem de Emails](#3-listagem-de-emails)
4. [Fluxo de Integração](#fluxo-de-integração)
5. [Exemplos de Código](#exemplos-de-código)
6. [Tratamento de Erros](#tratamento-de-erros)

---

## Visão Geral

A PhishForge API é uma solução para treinamento de conscientização em cibersegurança. Ela permite:

- **Gerar** exemplos realistas de emails de phishing com diferentes níveis de dificuldade
- **Avaliar** as justificativas dos usuários sobre identificação de phishing, retornando uma nota de 0 a 5

### Base URL

```
http://seu-servidor:8000
```

---

## Autenticação

Toda rota sob `/api/v1` -- geração, avaliação **e leitura** (listagem, detalhe, estatísticas)
-- exige o header `X-API-Key` (issue #7). O único cliente legítimo hoje é o backend Go,
chamando servidor-a-servidor; não há OAuth nem sessão de usuário.

```bash
curl -s http://seu-servidor:8000/api/v1/emails \
  -H "X-API-Key: sua-chave-aqui"
```

| Situação | Resposta |
|----------|----------|
| Header ausente ou chave incorreta | **401 Unauthorized** |
| `API_KEY` não configurada no servidor | **503 Service Unavailable** -- falha fechado, nunca equivalente a "sem autenticação" |
| Chave correta | segue normalmente |

Configuração via variável de ambiente `API_KEY` (ver `.env.example`). Não há endpoint de
emissão de chave nem rotação automática -- é um segredo compartilhado, distribuído fora de
banda entre os operadores dos dois serviços.

---

## Endpoints Disponíveis

### 1. Geração de Phishing

#### POST `/api/v1/generate`

Gera um único exemplo de email de phishing personalizado usando um pipeline RAG avançado.

**Request Body:**

```json
{
  "user_context": "Funcionário de banco que recebeu email sobre atualização de dados",
  "difficulty": "medio",
  "is_malicious": true
}
```

| Campo | Tipo | Obrigatório | Descrição |
|-------|------|-------------|-----------|
| `user_context` | string | Sim | Contexto/cenário para geração do item |
| `difficulty` | string | Sim | Nível: `facil`, `medio` ou `dificil` (ver [Vocabulário de dificuldade](#vocabulário-de-dificuldade)) |
| `is_malicious` | boolean | Não (default `true`) | `true` gera phishing; `false` gera item **legítimo** (comunicação real, sem pedido de credencial nem link malicioso -- necessário para medir taxa de falso alarme e d-prime) |
| `channel` | string | Não (default `email`) | Canal do item -- ver [Canais suportados](#canais-suportados-channel) |

**Response (200 OK):**

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "receptor": "joao.silva@empresa.com.br",
  "remetente": "suporte@banc0-brasil.com",
  "assunto": "URGENTE: Atualização de Dados Cadastrais",
  "conteudo": "Prezado(a) Cliente...",
  "explicacao": "Este email utiliza táticas de urgência e personificação...",
  "nivel": "medio",
  "categoria": "financeiro",
  "links": [
    {"text": "Atualizar meus dados agora", "href": "http://banc0-brasil.com.phishing-site.net/atualizar"}
  ],
  "is_malicious": true,
  "cues": [
    {
      "code": "urgency",
      "evidencia": "URGENTE",
      "span_start": 0,
      "span_end": 7
    },
    {
      "code": "typosquat",
      "evidencia": "banc0-brasil.com",
      "span_start": null,
      "span_end": null
    }
  ],
  "phish_scale": {
    "cue_count": 2,
    "premise_alignment": "medio",
    "difficulty_estimated": "medio"
  }
}
```

Exemplo de item **legítimo** (`is_malicious: false`) para o mesmo contexto:

```json
{
  "id": "660f9511-f3ac-52e5-b827-557766551111",
  "receptor": "joao.silva@empresa.com.br",
  "remetente": "suporte@bancodobrasil.com.br",
  "assunto": "Confirmação de atualização de dados cadastrais",
  "conteudo": "Prezado João, confirmamos que seus dados cadastrais foram atualizados com sucesso. Se você não reconhece esta solicitação, acesse o aplicativo oficial do banco ou ligue para o SAC pelo número no verso do seu cartão. Nunca pedimos sua senha por e-mail ou telefone.",
  "explicacao": "Item confiável: domínio oficial do remetente, ausência de pedido de credencial, direcionamento ao aplicativo oficial e canal alternativo verificável (SAC).",
  "nivel": "facil",
  "categoria": "financeiro",
  "links": [],
  "is_malicious": false,
  "cues": [],
  "phish_scale": null
}
```

#### Links estruturados (`links`)

Desde a issue #5, cada item de `links` é um **objeto** com `text` (o texto exibido, o que a
vítima lê e clica) e `href` (o destino real) -- **não** mais uma string solta com só o destino.
Mudança quebra-contrato deliberada: não havia consumidor real desta API ainda (o backend Go
integra via `phishing-quest-api` #62, que ainda não existe), então o momento de trocar o shape
foi antes de existir um cliente para quebrar.

```json
"links": [
  {"text": "Atualizar meus dados agora", "href": "http://banc0-brasil.com.phishing-site.net/atualizar"}
]
```

Essa separação é o que habilita a pista `link_text_mismatch` (ver tabela abaixo): o texto do
link pode sugerir um destino diferente do `href` real, e o servidor consegue expressar essa
divergência em vez de só apontar "há um link suspeito".

#### Pistas anotadas (`cues`)

Além do texto livre em `explicacao`, cada item gerado traz `cues`: a lista estruturada das
pistas de phishing presentes, usando a taxonomia compartilhada com o backend Go
(`phishing-quest-api`) -- os mesmos 10 códigos, com os mesmos UUIDs fixos na tabela `cues`.

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `code` | string | Um dos 10 códigos canônicos (ver tabela abaixo) |
| `evidencia` | string | Trecho literal do `conteudo` que evidencia a pista |
| `span_start` / `span_end` | integer \| `null` | Posição (em caracteres) da evidência dentro de `conteudo`. **`null` quando o modelo não conseguiu localizar a pista com precisão** -- um destaque no lugar errado é pior que nenhum destaque, então o span é omitido em vez de arriscado |

**Códigos da taxonomia:**

| `code` | Categoria |
|--------|-----------|
| `sender_domain_mismatch` | technical |
| `typosquat` | technical |
| `homoglyph` | technical |
| `urgency` | psychological |
| `authority` | psychological |
| `generic_greeting` | psychological |
| `credential_request` | technical |
| `link_text_mismatch` | technical |
| `unexpected_attachment` | technical |
| `scarcity` | psychological |

Garantias do servidor (não é só instrução de prompt):

- Um item **legítimo** (`is_malicious: false`) **nunca** vem com `cues` não-vazio -- validado
  duas vezes (depois da geração e na persistência).
- Quando `span_start`/`span_end` vêm preenchidos, `conteudo[span_start:span_end]` sempre bate
  exatamente com `evidencia`. Se o modelo declarar um span que não corresponde ao texto real, o
  servidor descarta o span (fica `null`/`null`) mas **mantém a pista**.
- `link_text_mismatch` já é gerável: `links` passou a ser objeto com texto exibido e destino
  (ver [Links estruturados](#links-estruturados-links) acima).

#### Dificuldade estimada (`phish_scale`)

Até a issue #9, a dificuldade era **autodeclarada pelo LLM**: o modelo escrevia o item e
devolvia de volta o mesmo `nivel` que recebeu como instrução, sem nada verificar se o item
gerado como `dificil` de fato ficou mais difícil que um `facil`. `phish_scale` substitui esse
palpite pelos dois eixos objetivos do **NIST Phish Scale**:

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `cue_count` | integer | Quantidade de pistas do item (`= len(cues)`) -- nunca um número declarado à parte |
| `premise_alignment` | `baixo` \| `medio` \| `alto` | O quanto o pretexto do item se encaixa na rotina de quem recebe, julgado pelo LLM contra o `context`/`user_context` da request |
| `difficulty_estimated` | `facil` \| `medio` \| `dificil` | **Derivado** deterministicamente de `cue_count` + `premise_alignment` -- nunca um terceiro palpite do modelo |

`phish_scale` é `null` para item **legítimo** (`is_malicious: false`): "dificuldade de detectar
phishing" não se aplica a algo que não é phishing.

**Três campos de dificuldade, três significados diferentes -- não confundir:**

| Campo | Quando existe | O que significa |
|-------|----------------|------------------|
| `nivel` | Sempre | O nível **pedido** na request (`difficulty`) |
| `phish_scale.difficulty_estimated` | Item malicioso | Estimativa **a priori**, derivada dos dois eixos acima, no momento da geração |
| `difficulty_calibrated` (futuro, backend Go) | Após dados de tentativas reais | Dificuldade **medida a posteriori**, a partir da taxa de acerto de participantes (`phishing-quest-api` #66) |

Regra de derivação de `difficulty_estimated` (determinística, revisável quando houver dado
empírico de calibração):

| `cue_count` | pontos | `premise_alignment` | pontos | soma | `difficulty_estimated` |
|---|---|---|---|---|---|
| 0–1 | 2 | qualquer | — | — | — |
| 2 | 1 | qualquer | — | — | — |
| 3+ | 0 | qualquer | — | — | — |
| — | — | `alto` | 2 | — | — |
| — | — | `medio` | 1 | — | — |
| — | — | `baixo` | 0 | — | — |

A soma dos dois pontos decide o resultado: **0–1 → `facil`**, **2–3 → `medio`**, **4 →
`dificil`**.

#### Canais suportados (`channel`)

Além de email, a geração suporta os 5 outros canais do vocabulário compartilhado com o backend
Go (issue #6, completa desde que a `phishing-quest-api` #68 desbloqueou `sms`/`whatsapp`). Cada
canal tem seu próprio shape em `content_json` -- quando `channel` é diferente de `email`, os
campos `receptor`/`remetente`/`assunto`/`conteudo` vêm `null` e o conteúdo real está em
`content_json`.

| `channel` | Shape de `content_json` |
|-----------|--------------------------|
| `email` (default) | *(usa os campos antigos, não `content_json`)* |
| `website` | `{"url", "title", "visible_content"}` |
| `phone_call` | `{"caller", "transcript"}` |
| `pix_qr` | `{"payload", "recipient", "amount", "pix_key"}` -- `amount` é sempre **string** (ex.: `"149.90"`), nunca número |
| `sms` | `{"sender", "text", "links"}` -- `links` no mesmo shape de [Links estruturados](#links-estruturados-links) |
| `whatsapp` | `{"sender", "display_name", "messages"}` -- `messages` é um histórico: `[{"author": "contact" \| "user", "text"}]` |

Exemplo de resposta para `channel: "pix_qr"`:

```json
{
  "id": "...",
  "receptor": null,
  "remetente": null,
  "assunto": null,
  "conteudo": null,
  "explicacao": "...",
  "nivel": "dificil",
  "categoria": "financeiro",
  "channel": "pix_qr",
  "content_json": {
    "payload": "00020126...",
    "recipient": "Loja Falsa LTDA",
    "amount": "149.90",
    "pix_key": "loja@golpe.com"
  },
  "cues": [],
  "phish_scale": null,
  "is_malicious": true
}
```

Exemplo de resposta para `channel: "whatsapp"`:

```json
{
  "id": "...",
  "receptor": null,
  "remetente": null,
  "assunto": null,
  "conteudo": null,
  "explicacao": "...",
  "nivel": "medio",
  "categoria": "financeiro",
  "channel": "whatsapp",
  "content_json": {
    "sender": "+5511999990000",
    "display_name": "Suporte Banco",
    "messages": [
      {"author": "contact", "text": "Identificamos uma pendência em sua conta."},
      {"author": "user", "text": "Que pendência?"},
      {"author": "contact", "text": "Acesse o link para regularizar: bit.ly/xyz"}
    ]
  },
  "cues": [],
  "phish_scale": null,
  "is_malicious": true
}
```

`cues`/`phish_scale` ainda não existem para os 5 canais novos -- adaptar a taxonomia de pistas
por canal é decisão de pesquisa (ex.: `sender_domain_mismatch` não se aplica a Pix), fora do
escopo desta entrega.

#### POST `/api/v1/generate/batch`

Aceita um pedido de geração de múltiplos exemplos e processa **em background** (issue #11b). Um
`total` alto podia levar minutos rodando dentro de uma única conexão HTTP -- qualquer
ingress/proxy com timeout mais curto encerrava a conexão antes do fim, mesmo com os itens já
gravados no banco. Agora a request só cria o job e devolve **202 Accepted** com um `job_id`; o
progresso e o resultado final são obtidos por **polling** em `GET /api/v1/generate/batch/{job_id}`.

**Request Body:**

```json
{
  "context": "Ambiente corporativo de tecnologia",
  "difficulties": ["facil", "medio", "dificil"],
  "total": 9,
  "malicious_ratio": 0.7
}
```

| Campo | Tipo | Obrigatório | Descrição |
|-------|------|-------------|-----------|
| `context` | string | Sim | Contexto geral para geração |
| `difficulties` | array | Sim | Lista de dificuldades desejadas, não pode ser vazia (ver [Vocabulário de dificuldade](#vocabulário-de-dificuldade)) |
| `total` | integer | Não | Total de itens, entre 1 e 100 (padrão: 10) |
| `malicious_ratio` | float (0.0-1.0) | Não (default `1.0`) | Proporção de itens maliciosos vs. legítimos. Compõe com `difficulties`: dentro de cada nível, a fração `malicious_ratio` do total daquele nível é gerada como phishing e o restante como item legítimo |
| `channel` | string | Não (default `email`) | Canal do lote **inteiro** (não misto) -- ver [Canais suportados](#canais-suportados-channel) |

**Response (202 Accepted):**

```json
{
  "job_id": "9b458e37-be38-4487-8bc1-c8e30c1170ba",
  "status": "pendente"
}
```

#### GET `/api/v1/generate/batch/{job_id}`

Consulta o status e o resultado (parcial ou final) de um job criado pelo endpoint acima. O
cliente deve fazer polling neste endpoint até `status` chegar num valor terminal.

**Response (200 OK):**

```json
{
  "job_id": "9b458e37-be38-4487-8bc1-c8e30c1170ba",
  "status": "concluido",
  "channel": "email",
  "total_requested": 9,
  "total_generated": 9,
  "total_failed": 0,
  "total_discarded": 1,
  "distribution": {
    "facil": 3,
    "medio": 3,
    "dificil": 3
  },
  "examples": [
    {
      "id": "...",
      "receptor": "...",
      "remetente": "...",
      "assunto": "...",
      "conteudo": "...",
      "explicacao": "...",
      "nivel": "facil",
      "categoria": "...",
      "links": [...],
      "is_malicious": true,
      "cues": [...],
      "phish_scale": {...}
    }
  ],
  "failures": [
    {
      "difficulty": "medio",
      "is_malicious": true,
      "error": "Error code: 401 - Incorrect API key provided..."
    }
  ],
  "error_message": null,
  "created_at": "2026-09-18T20:00:00.000000+00:00",
  "updated_at": "2026-09-18T20:00:03.500000+00:00",
  "completed_at": "2026-09-18T20:00:03.500000+00:00"
}
```

Retorna **404 Not Found** se `job_id` não existir.

**Valores de `status`:**

| Valor | Significado |
|-------|--------------|
| `pendente` | Job criado, processamento ainda não começou |
| `em_progresso` | Processando; `total_generated`/`total_failed`/`total_discarded` refletem o progresso parcial (atualizados a cada item, não só no final) |
| `concluido` | Terminou sem nenhuma falha de geração |
| `concluido_com_falhas` | Terminou com pelo menos 1 item gerado e pelo menos 1 falha -- `failures` lista o que deu errado, sem interromper o restante do lote |
| `falhou` | Nenhum item foi gerado. Dois casos possíveis: (a) a etapa de montagem de contexto (normalização/HyDE/busca/fusão, compartilhada por todo o lote) lançou exceção antes de qualquer item ser tentado -- `error_message` traz o motivo e `distribution`/`examples`/`failures` ficam vazios; (b) todo item tentado foi descartado por duplicidade (ver abaixo) e nenhum falhou de fato |

**`total_discarded` -- deduplicação, distinto de falha:** cada item gerado é comparado (por
similaridade de cosseno entre embeddings) com os itens já aceitos no mesmo lote. Um item quase
idêntico a outro já aceito é re-gerado algumas vezes e, se continuar parecido demais, é
descartado -- contabilizado em `total_discarded`, **não** em `total_failed` nem em `failures`.
É uma categoria de resultado diferente de uma falha real de geração (erro de LLM, por exemplo),
que sempre aparece em `failures`.

**Retrocompatibilidade dentro do contrato anterior:** a distribuição entre dificuldades
(resto do `total` vai para as primeiras dificuldades da lista) e a composição de
`malicious_ratio` dentro de cada dificuldade continuam exatamente como antes da #11b -- só a
forma de obter o resultado final mudou, de resposta síncrona para polling.

#### Vocabulário de dificuldade

O valor **canônico** — o que é persistido no banco e o que aparece em qualquer resposta da API — é sempre um destes três:

| Valor canônico |
|----------------|
| `facil` |
| `medio` |
| `dificil` |

Para retrocompatibilidade com quem já integra em inglês, os seguintes sinônimos também são aceitos em `difficulty`/`difficulties` e normalizados automaticamente para o canônico correspondente **antes** de qualquer processamento:

| Sinônimo aceito | Normaliza para |
|------------------|-----------------|
| `easy`, `fácil` | `facil` |
| `medium`, `médio` | `medio` |
| `hard`, `difícil` | `dificil` |

Qualquer outro valor (`"muito_dificil"`, `"low"`, etc.) é rejeitado com **422 Unprocessable Entity** — a request não chega a gerar nada. Isso vale tanto para `POST /api/v1/generate` quanto para `POST /api/v1/generate/batch` (uma única dificuldade inválida na lista rejeita a lista inteira).

```bash
# 422 — nao 500, e nao gera nada
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:8000/api/v1/generate \
  -H "Content-Type: application/json" \
  -d '{"context": "cobranca de fatura", "difficulty": "nivel_inventado"}'
# -> 422
```

---

### 2. Avaliação de Respostas do Usuário

#### POST `/api/v1/evaluate/user-answer`

Avalia a **qualidade do raciocínio** do usuário sobre um item que pode ser phishing ou uma
comunicação legítima, retornando uma nota de 0 a 5.

> Antes da issue #4, este endpoint assumia que o item apresentado era sempre phishing --
> um usuário que acertasse um item legítimo seria avaliado contra o critério errado e zerado.
> Agora a avaliação depende do rótulo verdadeiro (`is_malicious`) e do veredito do usuário
> (`user_verdict`), cobrindo as quatro combinações possíveis.

**Request Body:**

```json
{
  "item_content": "De: suporte@banc0-brasil.com\nAssunto: URGENTE: Atualização de Dados\n\nPrezado Cliente,\n\nIdentificamos uma inconsistência em seus dados cadastrais. Para evitar o bloqueio de sua conta, acesse o link abaixo e atualize suas informações em até 24 horas.\n\nhttp://banc0-brasil.com.phishing-site.net/atualizar\n\nAtenciosamente,\nSuporte Banco Brasil",
  "is_malicious": true,
  "user_verdict": true,
  "user_justification": "Acredito que é phishing porque o remetente usa 'banc0' com zero no lugar do 'o', o tom é muito urgente tentando me pressionar, e o link parece suspeito pois não é do domínio oficial do banco."
}
```

| Campo | Tipo | Obrigatório | Descrição |
|-------|------|-------------|-----------|
| `item_content` | string | Sim | O item (malicioso ou legítimo) apresentado ao usuário |
| `is_malicious` | boolean | Sim | Rótulo **verdadeiro** do item: `true` se é phishing, `false` se é legítimo |
| `user_verdict` | boolean | Sim | O que o usuário respondeu: `true` para "é phishing", `false` para "é legítimo" |
| `user_justification` | string | Sim | A justificativa do usuário para o veredito acima |

**Response (200 OK):**

```json
{
  "score": 4,
  "feedback": "Boa análise! Você identificou corretamente três indicadores importantes de phishing: o typosquatting no remetente (banc0 com zero), a tática de urgência para pressionar a vítima, e o link suspeito. Para uma nota máxima, você poderia também mencionar a solicitação de dados sensíveis e a ameaça de bloqueio como gatilhos psicológicos.",
  "strengths": [
    "Identificou o typosquatting no domínio do remetente",
    "Reconheceu a tática de urgência como sinal de alerta",
    "Analisou corretamente o link suspeito"
  ],
  "improvements": [
    "Mencionar a solicitação implícita de dados sensíveis",
    "Identificar o gatilho psicológico de medo (ameaça de bloqueio)",
    "Analisar a falta de personalização no email"
  ],
  "acerto_por_sorte": false
}
```

**Exemplo com item LEGÍTIMO** (`is_malicious: false`) -- este é o caso que, antes da issue #4,
seria zerado mesmo com raciocínio correto:

```bash
curl -s -X POST localhost:8000/api/v1/evaluate/user-answer \
  -H "Content-Type: application/json" \
  -d '{
    "item_content": "De: rh@empresa.com.br\nAssunto: Avaliacao de desempenho\n\nAcesse o portal interno. Duvidas: ramal 4500.",
    "is_malicious": false,
    "user_verdict": false,
    "user_justification": "E legitimo: dominio oficial da empresa, nao pede senha e da um ramal para confirmar."
  }' | jq '{score, feedback}'
```

```json
{
  "score": 5,
  "feedback": "Excelente! Você identificou corretamente os sinais de legitimidade: domínio oficial da empresa, ausência de pedido de credencial e um canal alternativo verificável (o ramal) para confirmar a autenticidade."
}
```

**Escala de Notas** (mede qualidade da argumentação, aplicável às quatro combinações
rótulo × veredito):

| Nota | Classificação | Descrição |
|------|---------------|-----------|
| 0 | Incorreto | Justificativa sem relação com o item apresentado |
| 1 | Muito Fraco | Apenas um ponto superficial mencionado, sem embasar no item real |
| 2 | Fraco | Poucos elementos identificados vagamente |
| 3 | Satisfatório | Alguns elementos corretos (pistas de phishing OU sinais de legitimidade), argumentação básica |
| 4 | Bom | Múltiplos elementos corretos, boa articulação |
| 5 | Excelente | Análise completa e bem estruturada, cobrindo os elementos relevantes do item |

**Sobre `acerto_por_sorte`:** `true` quando o veredito do usuário bate com o rótulo verdadeiro,
mas a justificativa não sustenta essa conclusão (ex.: disse "é phishing" corretamente, mas por um
motivo genérico que não corresponde a nada realmente presente no item). É diferente de errar: é
acertar a conclusão por um argumento que não a sustenta -- sempre `false` quando o veredito do
usuário não bateu com o rótulo verdadeiro.

**Restrição importante:** quando o item é legítimo, o `feedback` nunca afirma que existe um
indicador de phishing, typosquatting ou qualquer técnica de engenharia social -- porque nenhuma
delas existe ali. Um feedback que inventasse esse indicador ensinaria exatamente o viés de falso
alarme que este endpoint existe para não reforçar.

---

### 2.5 Taxonomia de Pistas

#### GET `/api/v1/cues`

Lista as pistas de phishing ativas, com a **definição operacional** de cada uma
(`descricao_pt`) -- escrita para que dois anotadores humanos cheguem à mesma decisão dado o
mesmo trecho de texto. Mesmos 10 códigos e UUIDs do backend Go. Exige `X-API-Key`, como as
demais rotas.

```json
{
  "cues": [
    {
      "id": "00000000-0000-0000-0000-000000000002",
      "code": "typosquat",
      "label_pt": "Domínio com erro de digitação proposital (typosquatting)",
      "descricao_pt": "Domínio com um ou mais caracteres trocados, adicionados ou removidos de propósito...",
      "category": "technical",
      "ativo": true
    }
  ]
}
```

Ordenadas por `category` e depois por `code`. Uma pista com `ativo = false` não aparece aqui,
mas continua válida para o histórico que a referencia (`email_cues`).

### 2.6 Módulo de avaliação por especialistas (sessão e consentimento)

Rotas usadas por um **especialista no navegador**. Ficam num roteador separado e **não** exigem a
`X-API-Key` do backend Go (essa chave é servidor-a-servidor e nunca deve chegar a um navegador):
autenticam-se por um **JWT de sessão** (`Authorization: Bearer <token>`, HS256, 12h, sem refresh).

| Método / Path | Auth | Resumo |
|---|---|---|
| `POST /api/v1/expert/session` | — | `{codigo_acesso}` → `{token, expires_at, especialista, rodada, consentimento, perfil, progresso}` |
| `GET /api/v1/expert/me` | Bearer | Mesmo corpo, sem `token` |
| `GET /api/v1/expert/tcle` | Bearer | `{versao, texto_md}` |
| `POST /api/v1/expert/consentimento` | Bearer | `{versao, aceito}` — 422 se `aceito=false`, 409 se `versao` não for a vigente |
| `POST /api/v1/expert/perfil` | Bearer | `{anos_experiencia, area_atuacao, formacao}` |
| `POST /api/v1/expert/revogacao` | Bearer | Autoatendimento LGPD; idempotente, vale imediatamente |

- O **código de acesso** (`XXXX-XXXX-XXXX-XXXX`, sem caracteres ambíguos) é entregue em claro uma única
  vez, ao ser criado; só o SHA-256 fica gravado. Maiúsculas/minúsculas e traços são ignorados.
- `401` tem a **mesma** mensagem para código inexistente, revogado, token inválido e expirado.
- `409`: especialista sem rodada, ou rodada que não está `aberta`.
- `503` em **todas** as rotas se `EXPERT_JWT_SECRET` estiver vazio (fail-closed: não existe segredo
  default). O console do pesquisador usa `X-API-Key` contra `RESEARCHER_API_KEY`, **distinta** de `API_KEY`.
- `consentimento.necessario` volta a `true` quando o TCLE muda de versão no meio da coleta.
- `progresso` é `{total, concluidas: 0, proxima_ordem: 1}` até a issue #37 introduzir as avaliações.

Variáveis: `EXPERT_JWT_SECRET`, `EXPERT_JWT_EXPIRES_HOURS` (12), `RESEARCHER_API_KEY`,
`EXPERT_FRONTEND_URL` — ver `.env.example`.

### 3. Listagem de Emails

#### GET `/api/v1/emails`

Lista emails de phishing gerados anteriormente.

**Query Parameters:**

| Parâmetro | Tipo | Descrição |
|-----------|------|-----------|
| `categoria` | string | Filtrar por categoria |
| `nivel` | string | Filtrar por dificuldade |
| `search` | string | Busca textual |
| `limit` | integer | Limite de resultados (máx: 100) |
| `offset` | integer | Offset para paginação |

**Response (200 OK):**

```json
{
  "emails": [...],
  "count": 50
}
```

#### GET `/api/v1/emails/{email_id}`

Busca um email específico por ID. Inclui `cues` (ver [Pistas anotadas](#pistas-anotadas-cues)) e `phish_scale` (ver [Dificuldade estimada](#dificuldade-estimada-phish_scale)).

> `GET /api/v1/emails` e as demais listagens filtradas (`categoria`, `nivel`, `search`) **não**
> incluem `cues` -- só a busca por id e o `examples` do resultado do lote
> (`GET /api/v1/generate/batch/{job_id}`) fazem essa junção.

#### GET `/api/v1/emails/statistics`

Retorna estatísticas dos emails gerados.

---

## Fluxo de Integração

### Fluxo Completo de Treinamento

```
┌─────────────────────────────────────────────────────────────────┐
│                    SISTEMA DE TREINAMENTO                        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  1. GERAR EXEMPLO DE PHISHING                                   │
│     POST /api/v1/generate                                       │
│     - Definir contexto e dificuldade                            │
│     - Receber email de phishing gerado                          │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  2. APRESENTAR AO USUÁRIO                                       │
│     - Exibir o email de phishing                                │
│     - Solicitar que identifique se é phishing                   │
│     - Pedir justificativa da resposta                           │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  3. AVALIAR RESPOSTA DO USUÁRIO                                 │
│     POST /api/v1/evaluate/user-answer                           │
│     - Enviar exemplo + justificativa do usuário                 │
│     - Receber nota (0-5) e feedback detalhado                   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  4. EXIBIR RESULTADO                                            │
│     - Mostrar nota ao usuário                                   │
│     - Exibir feedback com pontos fortes e melhorias             │
│     - Mostrar explicação oficial do phishing                    │
└─────────────────────────────────────────────────────────────────┘
```

---

## Exemplos de Código

### Python

```python
import requests

BASE_URL = "http://localhost:8000"

# 1. Gerar exemplo de phishing
def generate_phishing(context: str, difficulty: str) -> dict:
    response = requests.post(
        f"{BASE_URL}/api/v1/generate",
        json={
            "user_context": context,
            "difficulty": difficulty
        }
    )
    response.raise_for_status()
    return response.json()

# 2. Avaliar resposta do usuário
def evaluate_answer(item_content: str, is_malicious: bool, user_verdict: bool, user_justification: str) -> dict:
    response = requests.post(
        f"{BASE_URL}/api/v1/evaluate/user-answer",
        json={
            "item_content": item_content,
            "is_malicious": is_malicious,
            "user_verdict": user_verdict,
            "user_justification": user_justification
        }
    )
    response.raise_for_status()
    return response.json()

# Exemplo de uso
if __name__ == "__main__":
    # Gerar phishing
    phishing = generate_phishing(
        context="Funcionário de RH recebendo email sobre folha de pagamento",
        difficulty="medio"
    )
    print(f"Email gerado: {phishing['assunto']}")
    
    # Simular justificativa do usuário
    email_completo = f"""
    De: {phishing['remetente']}
    Assunto: {phishing['assunto']}
    
    {phishing['conteudo']}
    """
    
    justificativa = "O email é suspeito porque pede informações urgentes e tem um link estranho"
    
    # Avaliar resposta (o usuário identificou corretamente o item malicioso)
    avaliacao = evaluate_answer(
        item_content=email_completo,
        is_malicious=phishing["is_malicious"],
        user_verdict=True,
        user_justification=justificativa,
    )
    print(f"Nota: {avaliacao['score']}/5")
    print(f"Feedback: {avaliacao['feedback']}")
```

### JavaScript/TypeScript

```typescript
const BASE_URL = "http://localhost:8000";

interface LinkRef {
  text: string;
  href: string;
}

interface PhishingEmail {
  id: string;
  receptor: string;
  remetente: string;
  assunto: string;
  conteudo: string;
  explicacao: string;
  nivel: string;
  categoria: string;
  links: LinkRef[];
  is_malicious: boolean;
}

interface EvaluationResult {
  score: number;
  feedback: string;
  strengths: string[];
  improvements: string[];
  acerto_por_sorte: boolean;
}

// Gerar exemplo de phishing
async function generatePhishing(
  context: string, 
  difficulty: string
): Promise<PhishingEmail> {
  const response = await fetch(`${BASE_URL}/api/v1/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      user_context: context,
      difficulty: difficulty
    })
  });
  
  if (!response.ok) throw new Error("Falha ao gerar phishing");
  return response.json();
}

// Avaliar resposta do usuário
async function evaluateAnswer(
  itemContent: string,
  isMalicious: boolean,
  userVerdict: boolean,
  userJustification: string
): Promise<EvaluationResult> {
  const response = await fetch(`${BASE_URL}/api/v1/evaluate/user-answer`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      item_content: itemContent,
      is_malicious: isMalicious,
      user_verdict: userVerdict,
      user_justification: userJustification
    })
  });
  
  if (!response.ok) throw new Error("Falha ao avaliar resposta");
  return response.json();
}

// Exemplo de uso
async function runTraining() {
  // Gerar phishing
  const phishing = await generatePhishing(
    "Ambiente corporativo de tecnologia",
    "dificil"
  );
  
  // Criar texto completo do email
  const emailCompleto = `
    De: ${phishing.remetente}
    Assunto: ${phishing.assunto}
    
    ${phishing.conteudo}
  `;
  
  // Avaliar justificativa do usuário (identificou corretamente o item malicioso)
  const avaliacao = await evaluateAnswer(
    emailCompleto,
    phishing.is_malicious,
    true,
    "O domínio do remetente parece falso e o email pede ações urgentes"
  );
  
  console.log(`Nota: ${avaliacao.score}/5`);
  console.log(`Feedback: ${avaliacao.feedback}`);
}
```

### cURL

```bash
# Gerar exemplo de phishing
curl -X POST "http://localhost:8000/api/v1/generate" \
  -H "Content-Type: application/json" \
  -d '{
    "user_context": "Email para funcionário do departamento financeiro",
    "difficulty": "medio"
  }'

# Avaliar resposta do usuário
curl -X POST "http://localhost:8000/api/v1/evaluate/user-answer" \
  -H "Content-Type: application/json" \
  -d '{
    "item_content": "De: financeiro@empresa-falsa.com\nAssunto: Pagamento Urgente\n\nPrecisamos que você autorize o pagamento anexo.",
    "is_malicious": true,
    "user_verdict": true,
    "user_justification": "O email parece suspeito porque pede autorização urgente e o domínio não é oficial."
  }'
```

---

## Tratamento de Erros

### Códigos de Status HTTP

| Código | Descrição |
|--------|-----------|
| 200 | Sucesso |
| 202 | Job de geração em lote aceito (`POST /api/v1/generate/batch`) -- resultado por polling em `GET /api/v1/generate/batch/{job_id}` |
| 400 | Requisição inválida (parâmetros faltando ou incorretos) |
| 401 | `X-API-Key` ausente ou incorreta (ver [Autenticação](#autenticação)) |
| 404 | Recurso não encontrado (inclui `job_id` inexistente em `GET /api/v1/generate/batch/{job_id}`) |
| 422 | Corpo da requisição não passa na validação (ex.: `difficulty` fora do [vocabulário aceito](#vocabulário-de-dificuldade)) |
| 429 | Limite de requisições excedido em `/generate`/`/generate/batch` (`GENERATION_RATE_LIMIT`, default 20/minuto por IP) |
| 500 | Erro interno do servidor |
| 503 | `API_KEY` não configurada no servidor -- toda rota fica indisponível até isso ser corrigido |

### Formato de Erro

```json
{
  "detail": "Descrição do erro"
}
```

### Boas Práticas

1. **Sempre trate exceções** nas chamadas à API
2. **Implemente retry** com backoff exponencial para erros 5xx
3. **Valide os dados** antes de enviar para a API
4. **Armazene os IDs** dos emails gerados para referência futura

---

## Contato e Suporte

Para dúvidas ou problemas com a integração, consulte a documentação técnica em `/docs/architecture.md` ou abra uma issue no repositório do projeto.
