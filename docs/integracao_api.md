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

Atualmente a API não requer autenticação. Em ambientes de produção, recomenda-se implementar autenticação via API Key ou OAuth2.

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
  "links": ["http://banc0-brasil.com.phishing-site.net/atualizar"],
  "is_malicious": true
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
  "is_malicious": false
}
```

#### POST `/api/v1/generate/batch`

Gera múltiplos exemplos de phishing em lote.

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
| `difficulties` | array | Sim | Lista de dificuldades desejadas (ver [Vocabulário de dificuldade](#vocabulário-de-dificuldade)) |
| `total` | integer | Não | Total de itens (máx: 100, padrão: 10) |
| `malicious_ratio` | float (0.0-1.0) | Não (default `1.0`) | Proporção de itens maliciosos vs. legítimos. Compõe com `difficulties`: dentro de cada nível, a fração `malicious_ratio` do total daquele nível é gerada como phishing e o restante como item legítimo |

**Response (200 OK):**

```json
{
  "total_requested": 9,
  "total_generated": 9,
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
      "is_malicious": true
    }
  ]
}
```

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

Busca um email específico por ID.

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

interface PhishingEmail {
  id: string;
  receptor: string;
  remetente: string;
  assunto: string;
  conteudo: string;
  explicacao: string;
  nivel: string;
  categoria: string;
  links: string[];
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
| 400 | Requisição inválida (parâmetros faltando ou incorretos) |
| 404 | Recurso não encontrado |
| 422 | Corpo da requisição não passa na validação (ex.: `difficulty` fora do [vocabulário aceito](#vocabulário-de-dificuldade)) |
| 500 | Erro interno do servidor |

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
