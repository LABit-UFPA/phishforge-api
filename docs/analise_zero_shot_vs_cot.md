# Análise Comparativa: Zero-Shot vs Chain-of-Thought Prompting

## 1. Introdução

Este documento apresenta os resultados do experimento comparativo entre duas técnicas de prompting para geração de emails de phishing educacionais:

- **Zero-Shot Prompting**: Prompt direto e simples, sem etapas estruturadas de raciocínio
- **Chain-of-Thought (CoT) Prompting**: Prompt com etapas explícitas de análise, seleção de táticas, construção e validação

### 1.1 Configuração do Experimento

| Parâmetro | Valor |
|-----------|-------|
| **Modelo** | GPT-4 |
| **Data** | 15/01/2026 |
| **Total de Avaliações** | 6 (3 por técnica de prompting) |
| **Níveis de Dificuldade** | Fácil, Médio, Difícil |
| **Métricas RAGAS** | Context Relevance, Faithfulness, Response Relevancy |
| **Modelo de Avaliação** | GPT-4o-mini |

---

## 2. Resultados Consolidados

### 2.1 Comparação por Técnica de Prompting

| Métrica | Zero-Shot | Chain-of-Thought | Diferença |
|---------|-----------|------------------|-----------|
| **Context Relevance** | 1.0000 | 1.0000 | 0.00 |
| **Faithfulness** | 0.1368 | 0.0333 | **+0.1035** (Zero-Shot melhor) |
| **Response Relevancy** | 0.3600 | 0.3596 | +0.0004 (≈ igual) |
| **Tempo Médio (s)** | 82.04 | 75.88 | +6.16s |

### 2.2 Comparação por Nível de Dificuldade

| Dificuldade | Context Relevance | Faithfulness | Response Relevancy | Tempo (s) |
|-------------|-------------------|--------------|-------------------|-----------|
| **Fácil** | 1.0000 | 0.1053 | 0.0000 | 78.72 |
| **Médio** | 1.0000 | 0.1500 | 0.5902 | 69.45 |
| **Difícil** | 1.0000 | 0.0000 | 0.4891 | 88.71 |

---

## 3. Análise Detalhada

### 3.1 Context Relevance (1.0 para ambos)

Ambas as técnicas alcançaram pontuação perfeita na relevância do contexto. Isso indica que:

- O pipeline RAG está funcionando corretamente
- Os documentos recuperados são altamente relevantes para as consultas de busca
- A técnica de prompting **não afeta** a qualidade da recuperação de contexto

**Conclusão**: O componente de retrieval é agnóstico ao tipo de prompting utilizado na geração.

### 3.2 Faithfulness (Zero-Shot: 0.137 vs CoT: 0.033)

O resultado mais surpreendente do experimento: **Zero-Shot apresentou Faithfulness 4x maior** que Chain-of-Thought.

| Técnica | Fácil | Médio | Difícil | Média |
|---------|-------|-------|---------|-------|
| Zero-Shot | 0.2105 | 0.2000 | 0.0000 | 0.1368 |
| CoT | 0.0000 | 0.1000 | 0.0000 | 0.0333 |

**Interpretação**:
- A métrica Faithfulness mede o quanto a resposta está fundamentada nos documentos de contexto
- O prompt Zero-Shot, por ser mais simples, pode forçar o modelo a aderir mais ao contexto fornecido
- O prompt CoT, com suas múltiplas etapas estruturadas, pode encorajar o modelo a "raciocinar além" do contexto, introduzindo elementos não presentes nos documentos
- Valores baixos em ambos (< 0.25) sugerem que ambas as técnicas geram conteúdo majoritariamente criativo, não factual

### 3.3 Response Relevancy (≈ 0.36 para ambos)

As duas técnicas apresentaram Response Relevancy praticamente idêntica:

| Técnica | Fácil | Médio | Difícil | Média |
|---------|-------|-------|---------|-------|
| Zero-Shot | 0.0000 | 0.6103 | 0.4697 | 0.3600 |
| CoT | 0.0000 | 0.5701 | 0.5086 | 0.3596 |

**Observações**:
- Nível Fácil: 0.0 em ambos → emails muito curtos ou simples para avaliação semântica adequada
- Nível Médio: ambos acima de 0.5 → melhor performance geral
- Nível Difícil: performance similar entre técnicas

**Conclusão**: A técnica de prompting não impacta significativamente a relevância da resposta em relação à pergunta do usuário.

### 3.4 Tempo de Execução

| Técnica | Tempo Médio | Diferença |
|---------|-------------|-----------|
| Zero-Shot | 82.04s | +8.1% mais lento |
| CoT | 75.88s | Referência |

Contraintuitivamente, o **Chain-of-Thought foi mais rápido** que o Zero-Shot. Possíveis explicações:
- Variabilidade natural da API OpenAI
- O prompt CoT, sendo mais estruturado, pode resultar em respostas mais previsíveis e eficientes
- A amostra pequena (n=3) não permite conclusões estatísticas robustas

---

## 4. Exemplos Gerados

### 4.1 Nível Fácil - Comparação

#### Zero-Shot
```
From: support@yourbnk.com
Subject: URGENT: Upddate Your Bank Registration DATA NOW!

Dear Costumer, 
We have detected issues with your bank account. To avoid freezing of your account, 
you must update your registration data immediately. 
Click here: www.yourbnk-update.com 
Do not ignore this message! Failure to comply will result in permanent account suspension.
```

#### Chain-of-Thought
```
From: noreply@yourbank123.com
Subject: URGETN: Update Your Registration Data!!!

Dear Valued Customer, 
We hve noticed some irregularities in your account. We need you to update your 
registration data immediately to prevent any service interruption. 
Please visit the following link to update your details: 
http://yourbank123-update-info.com
```

**Análise**: Ambos incluíram erros ortográficos intencionais (requisito do nível fácil). O Zero-Shot usou "Costumer" e "Upddate", enquanto o CoT usou "URGETN" e "hve". Ambos são igualmente eficazes para fins educacionais.

### 4.2 Nível Difícil - Comparação

#### Zero-Shot
```
From: Maria Santos <Maria.Santos@ourcompany.com>
Subject: Urgent: Project Expansion 2025 Transfer Request

Hello Pedro,
I hope this email finds you well. I am writing regarding an urgent matter that 
requires your immediate attention. Due to an unexpected situation, we need to 
make an immediate transfer for Project Expansion 2025.

Could you please log in to our financial system using the below link and transfer 
the amount of $50,000 to the account number 12345678, belonging to our partner 
company, Expansion Industries?

Link: www.ourcompany-finance.com
```

#### Chain-of-Thought
```
From: Maria Santos <maria.santos@company.com>
Subject: Urgent: Transfer Required for Expansion Project 2025

Hi Pedro,
I hope you're well. I'm currently in a meeting with the board, and we urgently 
need to secure some resources for the Expansion Project 2025. Can you immediately 
transfer $100,000 to the account details below?

Bank: Global Bank
Account No: 1234567890
Sort Code: 00-00-00

I trust you understand the importance of this.
```

**Análise**: 
- Zero-Shot: Inclui link de phishing, mais formal
- CoT: Fornece dados bancários diretamente, mais casual ("Hi Pedro")
- Ambos usam táticas de urgência e autoridade eficazmente
- O CoT parece levemente mais sofisticado no tom pessoal

---

## 5. Conclusões

### 5.1 Principais Achados

| Aspecto | Vencedor | Observação |
|---------|----------|------------|
| **Context Relevance** | Empate | Ambos perfeitos (1.0) |
| **Faithfulness** | Zero-Shot | 4x maior aderência ao contexto |
| **Response Relevancy** | Empate | Diferença < 0.01% |
| **Tempo de Execução** | CoT | 8% mais rápido |
| **Qualidade Subjetiva** | Empate | Ambos geram emails adequados |

### 5.2 Recomendações

1. **Para produção com RAG**: **Zero-Shot** é recomendado
   - Maior Faithfulness indica melhor uso do conhecimento recuperado
   - Prompt mais simples = menor custo de tokens
   - Manutenção mais fácil

2. **Para tarefas complexas sem RAG**: **Chain-of-Thought** pode ser preferível
   - Estrutura de raciocínio beneficia tarefas que requerem múltiplas etapas
   - Útil quando não há contexto externo para fundamentar

3. **Para fins educacionais**: **Ambos são adequados**
   - A qualidade dos emails gerados é comparável
   - A escolha pode depender de outros fatores (custo, manutenção, preferência)

### 5.3 Limitações do Experimento

- **Amostra pequena**: apenas 3 avaliações por técnica
- **Único modelo**: apenas GPT-4 foi testado
- **Métricas RAGAS**: podem não capturar totalmente a qualidade para tarefas criativas
- **Variabilidade da API**: resultados podem variar entre execuções

---

## 6. Dados Brutos

### 6.1 Arquivo JSON
Os resultados completos estão disponíveis em: `avaliacoes_antigas/resultados/zero_shot_vs_cot_20260115_234820.json`

### 6.2 Resumo Numérico

```
Zero-Shot:
  - Context Relevance:  1.0000
  - Faithfulness:       0.1368
  - Response Relevancy: 0.3600
  - Tempo Médio:        82.04s

Chain-of-Thought:
  - Context Relevance:  1.0000
  - Faithfulness:       0.0333
  - Response Relevancy: 0.3596
  - Tempo Médio:        75.88s
```

---

## 7. Referências

- Wei, J., et al. (2022). Chain-of-Thought Prompting Elicits Reasoning in Large Language Models. NeurIPS.
- Es, S., et al. (2023). RAGAS: Automated Evaluation of Retrieval Augmented Generation. arXiv.
- OpenAI (2024). GPT-4 Technical Report.

---

*Documento gerado automaticamente em 15/01/2026*
