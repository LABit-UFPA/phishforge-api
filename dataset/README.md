# Conjunto de phishing PhishForge — v3.1.1 (para o classificador)

Conjunto de **960 e-mails de phishing em português**, gerados pelo PhishForge para **validar os três rótulos
da aplicação**. Este README explica os arquivos, o formato
dos itens e o protocolo de geração, para quem for usar os exemplos num
classificador.

> **Leia a seção "⚠️ Antes de treinar um classificador" antes de usar.** Há
> três armadilhas que inflam a acurácia se ignoradas.

- **Itens gerados:** **960 úteis de 960** (3 células ficaram 15/16 por limite de
  tokens e foram completadas com 1 item de top-up cada — ver "Ressalvas").
- **Modelo gerador:** Claude Sonnet 4.6 (`claude-sonnet-4-6`), via instructor
  Mode.ANTHROPIC_JSON (sem thinking).
- **Versão do código:** commit `ac0e3a3` (gravado em cada item/lote).
- **Todos os itens são phishing** (`is_malicious = true`). **Não há e-mails
  legítimos neste conjunto.**

---

## 1. Arquivos e pastas

```
dataset/
├── README.md                 ← este arquivo
├── exports/                  ← 60 arquivos JSON, um por lote (16 itens cada)
│   ├── E1-F-A-01_AAAAMMDD_HHMMSS.json
│   ├── E1-M-A-01_...json
│   └── ... (60 no total)
├── registro_lotes_v31.csv    ← a planilha de registro (1 linha por lote)
├── run_completo.log          ← log do run (progresso)
└── (backups/)                ← dumps do banco, se houver
```

- **`exports/*.json`** — a fonte do conjunto. Cada arquivo é um **lote** com 16
  itens (campo `examples`), além do metadado do job. Arquivos com sufixo **`-TU`**
  (ex.: `E1-D-A-01-TU1_...`) são itens de **top-up** que completaram células que
  ficaram curtas (ver "Ressalvas") — trate-os como itens normais da mesma célula.
- **`registro_lotes_v31.csv`** — contagem por lote: itens gerados, utilizáveis,
  recusa branda, descartes por categoria, `git_commit`, semente, modelo. É o que
  amarra cada lote à sua célula (eixo/nível/cenário) e garante reprodutibilidade.
- **`phishforge_960.jsonl`** ⭐ **arquivo consolidado recomendado** — 1 item por
  linha, com TODOS os campos + as chaves de agrupamento já embutidas
  (`eixo`, `nivel_pedido`, `cenario`, `lote_id`) + a dificuldade recalibrada
  (ver seção 2). É a forma mais simples de carregar o conjunto inteiro.
- **`recalibracao_dificuldade.md`** — a proposta de recalibração de dificuldade
  e a decisão (Opção D).

### Nomenclatura dos arquivos/lotes

`E{eixo}-{nível}-{cenário}-{nn}` — ex.: **`E1-D-C-01`** = eixo **E1**, nível
**D**ifícil, cenário **C**, lote 01.

| Dimensão | Valores |
|---|---|
| **Eixo** (contexto) | E1 institucional acadêmico · E2 financeiro/Pix · E3 credenciais de TI/nuvem · E4 logística/cobrança · E5 seleção/oportunidade |
| **Nível** (pedido) | F (fácil) · M (médio) · D (difícil) |
| **Cenário** | A · B · C · D (4 variações de contexto por célula) |

5 eixos × 3 níveis × 4 cenários = **60 lotes** × 16 = **960 itens**. Uma
"célula" é eixo×nível (15 células de 64 itens = 4 cenários × 16).

---

## 2. Formato de um item

Carregar todos os itens (do arquivo consolidado — recomendado):

```python
import json
itens = [json.loads(l) for l in open("dataset/phishforge_960.jsonl", encoding="utf-8")]
print(len(itens))  # 960
# cada item já tem: eixo, nivel_pedido, cenario, lote_id,
# difficulty_estimated_original e difficulty_estimated_recalibrado
```

(Alternativa — a partir dos lotes crus em `exports/`, sem as chaves de
agrupamento: percorra `exports/*.json` e junte os `examples`.)

Cada item é um objeto assim (campos principais):

```jsonc
{
  "id": "ed07cd6c-...",                 // UUID do item
  "is_malicious": true,                 // SEMPRE true (todos são phishing)
  "nivel": "facil",                     // nível PEDIDO (facil|medio|dificil)

  // --- O E-MAIL (a "entrada" que o especialista/classificador vê) ---
  "remetente": "Secretaria <secretaria@vertinnnorte.net.br>",
  "receptor":  "aluno@...",
  "assunto":   "Pendência no recadastramento...",
  "conteudo":  "Prezado...\n\n...",     // corpo em texto puro (sem markdown)
  "links": [ { "text": "Portal...", "href": "https://acesso.vertinnnorte.net.br/..." } ],

  // --- OS RÓTULOS DA APLICAÇÃO (o que se quer validar; "prata") ---
  "cues": [                             // pistas anotadas, com evidência e posição
    { "code": "typosquat", "evidencia": "secretaria@vertinnnorte.net.br",
      "span_start": 26, "span_end": 56, "campo": "remetente" }
  ],
  "phish_scale": {                      // o Phish Scale (rótulos derivados)
    "cue_count": 7,
    "premise_alignment": "alto",        // baixo | medio | alto
    "difficulty_estimated": "medio"     // facil | medio | dificil (ESTIMADO pela regra)
  },

  // --- PROCEDÊNCIA / ground-truth-by-construction (metadados) ---
  "categoria": "...",                   // rótulo livre do LLM (descritivo)
  "explicacao": "...",                  // análise do item (NÃO mostrar ao anotador humano)
  "target_cues": ["generic_greeting","typosquat","scarcity"],  // pistas que a FICHA mirou
  "variation_spec": { ... },            // a ficha sorteada (instituicao, dominio_da_pista, etc.)
  "validacao": { ... }                  // o que o pipeline corrigiu (ver abaixo)
}
```

**Onde estão os rótulos da app** (os três que o estudo valida):
1. **Pistas** → `cues[]` (cada uma com `code`, `evidencia`, `campo`,
   `span_start/end`) e a contagem `phish_scale.cue_count`.
2. **Alinhamento da premissa** → `phish_scale.premise_alignment`.
3. **Dificuldade estimada** → **use `difficulty_estimated_recalibrado`** (regra
   aritmética sobre os dois acima; ≠ `nivel`, que é o que foi *pedido*). O rótulo
   original (`phish_scale.difficulty_estimated` / `difficulty_estimated_original`)
   colapsou em 2 classes (fácil 225 / médio 735 / difícil 0) porque o corte de
   "difícil" era inatingível dada a densidade de pistas; os cortes foram
   **recalibrados** (Opção D, aprovada) → **fácil 139 / médio 580 / difícil 241**.
   Ambos ficam no item; o original é preservado. Ver `recalibracao_dificuldade.md`.

> `explicacao` é a análise do próprio item — **não é entrada**; serve de
> procedência e não deve ir para um anotador humano às cegas.

### Taxonomia das pistas (`cues[].code`) — 10 códigos fechados

`sender_domain_mismatch`, `typosquat`, `homoglyph`, `urgency`, `authority`,
`generic_greeting`, `credential_request`, `link_text_mismatch`,
`unexpected_attachment`, `scarcity`.

Duas famílias, **medidas separadamente**:
- **Pistas de corpo** (urgency, authority, generic_greeting, credential_request,
  link_text_mismatch, unexpected_attachment, scarcity): anotadas pelo LLM, com
  trecho literal de evidência.
- **Pistas de domínio** (`typosquat`, `sender_domain_mismatch`): **completadas
  por construção** a partir do remetente/link da ficha (o LLM quase nunca as
  autoanota). `homoglyph` **NÃO** é completado por construção → aparece pouco
  (6 no conjunto) e **não dá para estimar precisão para ele** — reporte à parte.

O campo `validacao.cues_completadas_por_construcao` diz quais pistas daquele item
entraram por construção; `validacao.evidencias_nao_literais` diz quais ficaram
sem posição (span) por a evidência não ser trecho literal.

---

## 3. Como o conjunto foi gerado (protocolo v3.1.1, resumo)

- **Ficha-driven:** cada item recebe uma ficha sorteada (instituição fictícia,
  domínio, pistas-alvo) com semente registrada (`variation_spec` + `seed`). As
  instituições/domínios são **fictícios** (nunca marcas reais).
- **Anotação às cegas:** `cues`/`premise_alignment` vêm de uma 2ª chamada do LLM
  que só vê o item pronto (não a ficha).
- **Validações pós-geração:** remetente/destinatário com e-mail de verdade; sem
  marcadores de template; sem instituição real; sem domínio caricato; sem link de
  exemplo (`.example`/`example.com`/porta `:0`); sem auto-denúncia de "simulação"
  no corpo. Itens que violam são regerados.
- **Escala:** 16 itens/lote, 4 lotes/célula (1 por cenário), 60 lotes = 960.
- **Determinismo:** semente fixa a ficha e a amostra; a Anthropic não tem seed,
  então o TEXTO não é bit-reprodutível — por isso o item gerado fica persistido.

O protocolo completo está em `../Protocolo de geração PhishForge — v3.1.md`.

---

## 4. ⚠️ Antes de treinar um classificador (leia!)

1. **O conjunto é 100% phishing.** Não há e-mails legítimos. Um classificador
   phishing-vs-legítimo treinado com estes de um lado e legítimos de OUTRA fonte
   aprende a **diferença de origem**, não de phishing. Gere os legítimos pelo
   mesmo PhishForge, nos mesmos eixos/contextos (é o "Bloco A" do protocolo,
   ainda não gerado).
2. **Divida por GRUPO, nunca aleatório.** Itens do mesmo lote compartilham o
   contexto recuperado da base; itens do mesmo cenário compartilham vocabulário.
   Split aleatório coloca itens parecidos no treino e no teste → acurácia
   inflada. **Deixe cenários ou eixos inteiros fora do treino** — use os campos
   `eixo` / `cenario` / `lote_id` (já em cada item do `phishforge_960.jsonl`)
   como chave de agrupamento (ex.: `GroupKFold` por `eixo` ou `cenario`).
3. **Rótulo prata vs ouro.** Os rótulos daqui são da **aplicação (prata)** —
   servem para treino. O rótulo válido para **teste** é o do **especialista
   humano (ouro)**, que **ainda não existe** (a validação com especialistas é a
   etapa seguinte do projeto). Treinar e testar no rótulo da app só ensina a
   imitar a regra da app.
4. **Não misture versões/modelos.** Todos estes itens são do commit `ac0e3a3` +
   Sonnet 4.6. Se gerar mais com outro commit/modelo, anote e não junte sem
   registrar a diferença.

---

## 5. Ressalvas conhecidas

- **960/960 (com top-up):** 3 lotes vieram com 15/16 (E1-D-A, E2-F-A, E3-D-C) —
  1 item cada truncado por limite de tokens. Foram completados com 1 item de
  **top-up** cada, regerado no mesmo contexto/cenário e commit (`ac0e3a3`),
  deduplicado contra os itens existentes da célula. Esses itens estão em exports
  com sufixo **`-TU`** no nome (ex.: `E1-D-A-01-TU1_...json`) e linhas próprias
  no registro. As 15 células ficam com 64.
- **`homoglyph` raro (6 ocorrências):** só-LLM, não por construção — não estime
  precisão para ele.
- **13,7% das pistas sem posição literal** (`evidencias_nao_literais`): a
  evidência citada não é trecho literal do e-mail. A pista é mantida; o span
  fica nulo. É um indicador da confiabilidade do anotador automático.
- **3 assuntos repetidos** entre lotes (0,3%). Sem quase-duplicatas de corpo.
- **Rótulos de especialista ainda não existem** (ver item 3 da seção 4).

---

## 6. Ética e uso

Material **dual-use** (phishing realista). Mantenha em local de acesso restrito
à equipe; não publique os exemplos brutos sem combinar. Finalidade: pesquisa e
treinamento de conscientização (LABit-UFPA). As requisições de geração foram à
API da Anthropic.
