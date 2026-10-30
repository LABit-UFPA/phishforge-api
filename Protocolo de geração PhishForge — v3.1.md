# Protocolo de geração PhishForge — v3.1

Oct 29, 2026 · @Logan

## Emenda v3.1.1 (30/10/2026) — decisões aplicadas e orçamento

**Números que passam a valer (substituem 25/100/1.500 no corpo abaixo):** **16 itens por lote**, **4 lotes por célula = 64 por célula**, **960 no total** (15 células × 64). Ajuste de orçamento: com ~US$ 100 na Anthropic, 1.500 não cabe (~US$ 130–150); 960 cabe (~US$ 83, margem ~US$ 17) e ainda comporta a subamostra de 300–350 dos especialistas. Onde o corpo disser 1.500/100/25, leia **960/64/16**.

**Decisões (30/10/2026):**
1. **Pular smokes pagos**, exceto o 1º lote real (que vira o piloto observado — a comparação já cobriu os 5 eixos × 3 níveis). O 1º lote é também o 1º teste do caminho concorrente contra a API real.
2. **1º lote conta** só se nenhum código mudar depois (versão congelada); se revelar defeito e o código mudar, refaz (~US$ 1,5–2).
3. **Meta 960** (16/lote). Opção B (gerar até o crédito acabar): **não** (desbalanceia). Opção C (1.500): só com +US$ 40–50 depois, mesmo commit e modelo.
4. **Ordem por rodada de cenário** (A em todas as 15 células, depois B, C, D; níveis intercalados) — **desvio registrado** do "um eixo por sessão": se o dinheiro acabar, o conjunto fica equilibrado.
5. **Mecanismo:** driver scriptado (`script/gerar_lotes.py`) via `/generate/batch`, com a planilha da seção 8, `--limite`, retomada e parada automática em erro de crédito ou após 3 lotes seguidos com falha.
6. **Homoglyph:** aceitar como só-LLM; **não** implementar completação por construção agora (mexer no código descongelaria a versão). Reportar à parte; se raro, não estimar precisão.
7. **Domínio aos especialistas:** mostrar remetente e links como o leitor veria, **sem** o domínio oficial; pistas de domínio reportadas à parte.
8. **Fácil sem pista de domínio:** aceitar, **sem** regenerar; reportar a taxa.
9. **`difficulty_estimated`:** análise principal = regra aplicada às anotações humanas vs dificuldade percebida; rótulo da aplicação = análise secundária.
10. **Cenários B/C/D:** aprovados provisoriamente; falta confirmação formal do Renato.

**Ferramentas entregues (sem custo de API):** `script/gerar_lotes.py` (driver), `script/qc_dataset.py` (QC da seção 9), `script/testar_backup.sh` (teste de backup/restauração). A recontagem reproduzível da recusa branda está resolvida na seção 5.

---

Este protocolo gera 960 exemplos com o PhishForge para validar, contra especialistas, os três rótulos da aplicação (pistas, alinhamento da premissa e dificuldade estimada). A v3.1 mantém o desenho da v3 (5 eixos × 3 níveis × 100 exemplos → emenda v3.1.1: 64, 60 lotes de 16, as mesmas 60 strings de contexto) e incorpora o que a seleção do modelo gerador e a revisão do pipeline mostraram entre 27 e 29/10/2026.

## O que mudou da v3 para a v3.1

| Tema | v3 | v3.1 | Por quê |
| --- | --- | --- | --- |
| Modelo gerador | Exemplo `gpt-4o-mini-2024-07-18`, temperatura 0,7 | Claude Sonnet 4.6, com o identificador exato do Console anotado; temperatura padrão do modelo, que o pipeline não configura | Maior rendimento de itens utilizáveis na comparação de quatro modelos (seção 5) |
| Ficha de variação | Não tratada | Cada item recebe uma ficha sorteada (pistas-alvo, remetente, domínio), registrada com a semente | A frequência de cada pista é induzida pela ficha, não emerge do modelo |
| Origem das pistas | "Anotadas pelo LLM" | Pistas de corpo: LLM. Pistas de domínio por construção: só `typosquat` e `sender_domain_mismatch` (o `homoglyph` segue só pelo LLM — ver seção 2) | Precisão e revocação medem coisas diferentes nos dois grupos (seção 2) |
| Item utilizável | Não definido | Regra única: gerado, sem erro explícito e sem recusa branda | Recusa branda passa como item válido e distorce rendimento e dificuldade (seção 5) |
| Descartes | Só quase-duplicados no lote | Quatro categorias na planilha: duplicata, recusa ou neutralização, erro de validação, erro de infraestrutura | A conta dos 64 por célula só fecha assim (seção 8) |
| Artefatos visíveis | Não tratados | Conferência de links `.example`, `example.com`, porta `:0` e colchetes de placeholder | O especialista vê e-mail, assunto, remetente e links, e esses artefatos denunciam o item por motivo fora da taxonomia (seções 9 e 10) |
| Reprodutibilidade | Versão da aplicação | Commit (com `GIT_COMMIT` exportado antes do build), snapshot do modelo, mecanismo de saída estruturada e semente por lote | O `git_commit` veio `None` na rodada de comparação |
| Execução | Um lote por vez | Geração concorrente (8 em paralelo), backoff em erro de taxa e checkpoint por lote | Reduz a geração de \~60 h em série (≈1.130 gerações × 124 s) para \~7 h no total |
| Antes de gerar | Piloto de 10 itens | Piloto de 10 itens, smoke dos eixos E2 a E5 e um lote de 16 em E1-D-A | E1 e Difícil são onde todos os modelos mais perderam (seção 6) |

## Decisões que dependem do orientador

As decisões abaixo ainda não foram tomadas e devem ser anotadas no registro de lotes antes do primeiro lote final.

- Confirmar o Claude Sonnet 4.6 como gerador. Ele está garantido pelo fornecedor pelo menos até 17/02/2027, então o conjunto deve ser gerado antes disso.
- Como reportar a perda de itens no nível Difícil e no eixo E1, que concentram recusas e neutralizações.
- Mostrar ou não o domínio oficial aos especialistas, e tratar as pistas de domínio como verdade por construção.
- O que fazer com o nível Fácil sem pista de domínio: regenerar ou aceitar.
- Como `difficulty_estimated` entra na análise, dado que ela é regra aritmética sobre os outros dois rótulos.
- Tratamento de marcas reais e dados que pareçam pessoais (seção 9).

## 1. Objetivo e escopo

O objetivo é gerar 960 exemplos de phishing com o PhishForge, distribuídos em cinco eixos de contexto e nos três níveis de dificuldade, e depois confrontar os rótulos da aplicação com o julgamento de especialistas.

Este protocolo cobre:

- o pipeline de geração e a escolha do modelo (seção 5);
- a preparação do ambiente, o lote-piloto e o smoke (seção 6);
- as strings de contexto (seção 7);
- a execução, o registro e o backup (seção 8);
- o controle de qualidade do conjunto gerado (seção 9);
- a seleção e a anotação da amostra pelos especialistas (seção 10).

Fica fora do escopo o treino de classificadores. A seção 11 traz apenas as regras mínimas para que o conjunto possa ser reutilizado nesse tipo de análise sem viés.

Decisões que não estão previstas aqui, como mudar uma string, o modelo, a versão da aplicação ou o número de itens, são tomadas com o orientador do projeto e anotadas no registro de lotes antes de seguir.

## 2. Os três rótulos sob validação

Os três rótulos têm origens diferentes dentro da aplicação, e cada um é validado separadamente.

| Rótulo | Como a aplicação o produz | O que o especialista anota | Métrica |
| --- | --- | --- | --- |
| cues / cue\_count | Pistas de corpo: anotadas pelo LLM, cada uma com o trecho literal de evidência. Pistas de domínio `typosquat` e `sender\_domain\_mismatch`: completadas por construção a partir da ficha, quando o LLM não as anota. `homoglyph` NÃO é completado por construção (ver abaixo) | As pistas que encontra, com o trecho, sem ver as da aplicação | Precisão e revocação por código da taxonomia, reportadas em dois grupos (corpo e domínio) |
| premise\_alignment | Julgado pelo LLM em três classes, contra o contexto da requisição | A classe de alinhamento, depois de ler o contexto | Concordância de três classes (kappa ponderado) |
| difficulty\_estimated | Regra aritmética fixa sobre os dois rótulos acima, sem julgamento do LLM | A dificuldade percebida (fácil, médio ou difícil) | Se os pontos de corte da regra separam o que o especialista separa |

### Pistas de corpo e pistas de domínio

As duas famílias medem coisas diferentes e são reportadas separadamente. Nas pistas de corpo, precisão e revocação medem o anotador LLM. Nas de domínio, como a aplicação as completa por construção a partir do remetente e do link sorteados pela ficha, elas medem a regra e a ficha, e a revocação depende de o especialista enxergar o remetente e o link. Cada item registra quais pistas foram completadas por construção (`cues_completadas_por_construcao`).

Atenção: no código, só `typosquat` e `sender_domain_mismatch` são completados por construção (`item_validation.PISTAS_DE_DOMINIO`). O `homoglyph` está na taxonomia e pode ser pista-alvo, mas, como toda pista de domínio, o LLM quase nunca o autoanota e não há completação por construção para ele — então sua revocação tende a ficar perto de zero e deve ser reportada como pista só-LLM, não por construção. Decisão pendente com o orientador: aceitar essa limitação (reportar homoglyph como só-LLM) ou implementar a completação de homoglyph no pipeline (gerador de homóglifo análogo ao de typosquat) antes da geração final.

### Por que a dificuldade tem duas análises

Medir só o rótulo final mistura uma anotação de LLM com uma regra determinística, e um resultado ruim não diria qual das duas falhou. Por isso a análise da seção 10 aplica a mesma regra também sobre as anotações humanas:

- O LLM anota bem? Compara as pistas e o alinhamento da aplicação com os do especialista.
- A regra corta no lugar certo? Compara a regra aplicada às anotações humanas com a dificuldade percebida pelo especialista.

## 3. Desenho do conjunto

São 5 eixos × 3 níveis = 15 células de **64 exemplos** (emenda v3.1.1), com **320 por nível**. Cada célula é gerada em **4 lotes de 16**, e cada lote usa um cenário diferente (A, B, C ou D) escrito no grau de detalhe do nível.

| Eixo de contexto | Fácil | Médio | Difícil | Total |
| --- | --- | --- | --- | --- |
| E1 · Institucional acadêmico | 64 | 64 | 64 | 192 |
| E2 · Financeiro e Pix | 64 | 64 | 64 | 192 |
| E3 · Credenciais de TI e nuvem | 64 | 64 | 64 | 192 |
| E4 · Logística e cobrança de taxa | 64 | 64 | 64 | 192 |
| E5 · Seleção e oportunidade | 64 | 64 | 64 | 192 |
| Total | 320 | 320 | 320 | 960 |

### Por que estes cinco eixos

- **Semelhança com o que circula de verdade.** Serviços financeiros, webmail e nuvem, e logística aparecem entre os setores mais personificados nos relatórios de tendências de phishing, inclusive no relatório da APWG que já está no acervo indexado da aplicação. Ao escrever o trabalho, cite os números do relatório.
- **Rotina da população-alvo.** O PhishForge serve ao treinamento da comunidade universitária. Os eixos E1, E3 e E5 são rotinas dessa população. Sem rotina reconhecível, não há premissa alinhada, e o alinhamento fica preso nas classes baixas.
- **Cobertura da taxonomia.** Estimar precisão por código exige que cada código apareça vezes suficientes. Os eixos distribuem os dez códigos, e a ficha de variação (seção 5) sorteia as pistas-alvo de cada item dentro do que o eixo favorece.
- **Diversidade de alavanca psicológica.** Autoridade (E1, E3), medo de perda financeira (E2, E4), prazo e escassez (E1, E4, E5) e oportunidade (E5).
- **Canal.** A geração produz apenas e-mail, e os cinco eixos são naturais nesse canal.

| Eixo | Pistas que o eixo favorece |
| --- | --- |
| E1 · Institucional acadêmico | autoridade, urgência, escassez, domínio divergente |
| E2 · Financeiro e Pix | autoridade, pedido de credencial, typosquat, urgência |
| E3 · Credenciais de TI e nuvem | pedido de credencial, texto de link divergente, homoglifo |
| E4 · Logística e cobrança de taxa | urgência, anexo inesperado, domínio divergente |
| E5 · Seleção e oportunidade | escassez, saudação genérica, anexo inesperado |

Essa tabela é a expectativa de projeto, não um resultado. Como a ficha de variação sorteia as pistas-alvo, a frequência de cada código por eixo é em parte induzida por ela, e deve ser declarada assim no trabalho. A frequência efetiva é medida depois de cada sessão e ao fim da geração (seção 9).

### Taxonomia: o que é e o que não é pista anotável

Confirmado no código-fonte (`app/domain/models/cue.py:CueCode`, espelhado no phishing-quest-api, migration V20260917110000). A taxonomia tem dez códigos, em Enum fechado usado via saída estruturada:

`sender_domain_mismatch`, `typosquat`, `homoglyph`, `urgency`, `authority`, `generic_greeting`, `credential_request`, `link_text_mismatch`, `unexpected_attachment`, `scarcity`.

Não existe código para erro gramatical/ortográfico nem para remetente suspeito genérico, e, pelo Enum fechado, o LLM não consegue emitir um. Esses dois aparecem só como texto livre no prompt, entre as características de estilo do nível fácil (`response_generator.py:266-267`): orientam a escrita do e-mail, mas não viram pista anotada, sem evidência nem posição na tabela `cues`.

Isso não é um defeito a corrigir no código, e não exige regerar. Os dez códigos são táticas de sofisticação do atacante; erro gramatical e remetente genérico são o oposto, falhas que denunciam o golpe. Faz sentido que a regra de dificuldade conte táticas e não conte falhas: o nível fácil é justamente o que tem poucas táticas e muitas falhas visíveis. A `difficulty_estimated` continua válida. Isso exige coerência em dois pontos:

- No artigo e neste protocolo, descreva o nível fácil separando as duas camadas: poucas táticas anotadas (pistas) e sinais de estilo escritos no e-mail (erro gramatical, remetente genérico, URL suspeita) que não são pistas da taxonomia.
- Na anotação humana (seção 10), o especialista usa exatamente os dez códigos. Se marcasse erro gramatical ou remetente suspeito, mediria a aplicação contra um código que ela não pode emitir, e a revocação cairia por construção.

## 4. Como o detalhe do contexto gradua a dificuldade

A dificuldade estimada sai de dois eixos: a quantidade de pistas no exemplo e o alinhamento da premissa ao contexto. A quantidade de pistas é movida pela instrução de nível no prompt de geração e pela ficha de variação. O alinhamento é julgado contra a string de contexto digitada, e é por aí que o detalhe do contexto age.

| Nível | O que a string contém | Efeito pretendido |
| --- | --- | --- |
| Fácil | Apenas o setor e o assunto; sem destinatário, rotina ou prazo | Premissa genérica, alinhamento baixo ou médio |
| Médio | Destinatário e situação; sem gatilho temporal nem referência interna concreta | Premissa plausível, mas não rotineira |
| Difícil | Destinatário, instituição, rotina, gatilho temporal e referência concreta | Premissa dentro da rotina, alinhamento alto |

Cada cenário (A a D) é escrito nos três graus de detalhe. Assim, dentro de um mesmo cenário, a única diferença entre os níveis é o detalhe, e a análise pode comparar níveis controlando pelo cenário.

### O que o desenho permite e não permite concluir

- O detalhe do contexto acompanha o nível pedido. Por isso, a concordância entre nível pedido e dificuldade estimada fica em parte embutida no desenho.
- Essa concordância deve ser reportada como evidência de que o gerador respondeu à manipulação, e não de que o rótulo está correto.
- A correção dos rótulos só se estabelece contra a anotação humana (seção 10).
- O nível é movido por três alavancas ao mesmo tempo: a instrução, o detalhe do contexto e a ficha de variação. Separar o efeito de cada uma exige o bloco opcional B (seção 11).
- Itens que o pipeline recusa ou neutraliza não contam como exemplo do nível pedido. Um item sem pistas por recusa branda sairia com `cue_count = 0` e `difficulty_estimated = "dificil"`, o que distorceria a análise; por isso a regra de item utilizável (seção 5) vale antes de qualquer contagem por nível.

## 5. Pipeline de geração e seleção do modelo

O gerador escolhido é o Claude Sonnet 4.6. Na comparação de 29/10/2026 entre quatro modelos, ele teve o maior rendimento de itens utilizáveis (40 de 45, 89%), aderência plena às pistas de corpo e nenhum artefato visível ao especialista. A escolha ainda precisa da confirmação do orientador (seção inicial).

### Configuração a congelar

| Item | Valor |
| --- | --- |
| Modelo | Claude Sonnet 4.6, com o identificador exato do Console (a anotar antes do primeiro lote) |
| Temperatura | Padrão do modelo; o pipeline não a configura, porque os modelos Claude 4.6 em diante e os GPT-5 em diante não aceitam outro valor |
| Saída estruturada | Biblioteca `instructor`, modo `ANTHROPIC_JSON`; sem `thinking` |
| Versão do gerador | `2026-10-29-prod-sonnet` (PR #72) |
| Commit | Hash exportado em `GIT_COMMIT` antes do build e gravado no metadata de cada lote |
| Concorrência | `BATCH_CONCURRENCY=8`, backoff em erro de taxa, checkpoint por lote (PR #74 — o #73 foi mergeado no branch errado e reaberto no #74) |
| Disponibilidade do modelo | Garantida pelo fornecedor pelo menos até 17/02/2027; gerar o conjunto antes disso |

### Ficha de variação

Cada item recebe uma ficha sorteada antes da geração, em ordem de posição no lote, com as pistas-alvo, o remetente e o domínio da pista. A semente e a ficha ficam no metadata do item. O LLM recebe a ficha como instrução, e as pistas de domínio que ele não realizar são completadas por construção depois da validação, para que as pistas novas tenham posição calculada.

### Item utilizável

Um item é utilizável quando foi gerado, não teve erro explícito e não é recusa branda. Recusa branda é o item aceito pelo pipeline com e-mail sanitizado (sem link, sem pistas, com conselho de segurança no corpo) ou com `explicacao` do tipo "não posso criar" ou "versão segura", ou sem `phish_scale`. Só itens utilizáveis contam para os 64 por célula e seguem para os especialistas.

### Resultado da comparação de modelos

Amostra: 45 contextos por modelo (15 células × 3 cenários), uma repetição, semente 42, mesma ficha nos quatro modelos, código congelado (`2026-10-29-piloto6-antidisclaimer`).

| Modelo | Utilizáveis | IC 95% | Falhas explícitas | Recusa branda |
| --- | --- | --- | --- | --- |
| Claude Sonnet 4.6 | 40/45 (89%) | 77–95% | 5 | 0 |
| GPT-6 Sol | 26/45 (58%) | 43–71% | 8 | 11 |
| GPT-6 Luna | 23/45 (51%) | 37–65% | 7 | 15 |
| Claude Haiku 5.5 | 20/45 (44%) | 31–59% | 24 | 1 |

O Sonnet 4.6 superou o Sol em 16 contextos contra 2 (teste do sinal, p = 0,0013) e o Haiku em 21 contra 1; Sol, Haiku e Luna não se distinguem entre si. Três itens do Sonnet em disputa (Difícil sem pista de corpo anotada) dão a faixa honesta de 37 a 40 de 45 (82–89%). Os dois juízes, de fornecedores diferentes, produziram o mesmo ranking (Spearman por item 0,765), o que torna improvável que a preferência de fornecedor dirija o resultado; isso não equivale a ausência de viés.

> **Recontagem reproduzível (resolvido, 30/10/2026).** A regra de recusa branda da seção 5 foi aplicada de forma reproduzível aos itens `ok` do JSON (`comparacao_modelos_20261029_185014.json`): recusa branda = e-mail sanitizado (sem link **e** sem pista) **ou** `explicacao` com recusa explícita do modelo (regex: "não posso", "versão segura", "cannot create", "as an AI", "not able to"; a menção a "simulação/conscientização" no campo `explicacao` NÃO conta, pois ali é análise legítima) **ou** sem `phish_scale`. Resultado — **Sonnet 40 (0 branda), Sol 25, Luna 23, Haiku 19** utilizáveis de 45. Isto confirma a tabela acima dentro de ±1 (Sol 26, Haiku 20) e sepulta a divergência da Luna (é **23**, não 12 — a estimativa anterior usava um critério manual mais rígido). A conclusão do Sonnet (1º, folgado) é robusta a qualquer critério.

### Limitações a declarar

- Uma repetição por contexto e 45 contextos por modelo: os intervalos são largos.
- A recusa branda é uma classificação dos autores, revisada por amostragem.
- O Sonnet 4.6 é de geração anterior aos GPT-6 e ao Haiku 5.5; o Sonnet 5.5 não pôde ser avaliado por saída vazia errática. A conclusão vale dentro do conjunto testado.
- A saída estruturada difere entre fornecedores (nativa na OpenAI, `instructor` na Anthropic).
- O Haiku foi avaliado sob a regra anti-disclaimer, que pode ter elevado as recusas dele.
- O GPT-4o mini entra como linha de base em rodada separada, com o mesmo commit, e só depois da seleção.

### Correções do pipeline antes da geração final

- Rótulos entre colchetes na assinatura (por exemplo `[SISTEMA ANR]`) são desembrulhados apenas quando contêm uma palavra de sistema ou a sigla da ficha; placeholders como `[LINK]` e `[SEU NOME]` continuam sendo rejeitados.
- Links inválidos (`.example`, `example.com`, porta `:0`, sem domínio) disparam regeneração; `mailto:`, `tel:` e `sms:` são aceitos.
- A completação de pistas de domínio roda depois da validação. Na comparação ela completou zero pistas em todos os modelos, e isso deve ser verificado no piloto.
- A geração concorrente desfaz a reserva de embedding e assunto quando a gravação falha.

### Custo e tempo (estimativa)

Com cerca de 8.500 tokens de entrada e 3.300 de saída por item, os **960** itens (emenda v3.1.1) custam cerca de **US$ 72** se nenhum for refeito. Como o rendimento esperado é de 85 a 89%, contam-se cerca de **1.130 gerações, ou US$ 83–90** (preços de terceiros, a conferir no painel) — dentro do saldo de ~US$ 100, com margem de ~US$ 17. O custo real por item será medido no 1º lote (painel da Anthropic). Com 8 chamadas em paralelo, o conjunto leva cerca de **4–5 horas**. Os limites de taxa do tier da Anthropic precisam ser conferidos antes do primeiro lote. (Para 1.500, seria ~US$ 130–150 — só com recarga extra, decisão 3/opção C.)

## 6. Antes de começar

Nenhum lote do conjunto final roda antes de todos os itens abaixo estarem marcados.

- [ ] Taxonomia confirmada com o orientador (lacuna da seção 3).
- [ ] Modelo gerador confirmado pelo orientador e identificador exato do Sonnet 4.6 anotado, com temperatura padrão registrada.
- [ ] Versão da aplicação congelada: PRs #72 e #74 integradas na `main` (o #73 foi mergeado no branch errado; o item 6 chegou à `main` pelo #74), `GIT_COMMIT` exportado antes do build e nenhuma atualização até o último lote.
- [ ] Limites de taxa do tier da Anthropic conferidos no Console; `BATCH_CONCURRENCY` ajustado se o limite for baixo.
- [ ] Cenários B, C e D escritos e aprovados pelo orientador (seção 7).
- [ ] Planilha de registro de lotes criada (seção 8).
- [ ] Backup testado: uma cópia do banco feita e restaurada com sucesso em um ambiente de teste.
- [ ] Orçamento de API aprovado, com base no custo por item medido no piloto.
- [ ] Cuidados da seção 11 combinados com o orientador.

### Lote-piloto e smoke

**Emenda v3.1.1 (decisão 1): os smokes pagos foram cancelados por orçamento.** A comparação já cobriu os 5 eixos × 3 níveis, e os smokes 1 e 2 (29/10) validaram o caminho de produção. Em vez dos três passos abaixo, **o 1º lote REAL (16 itens, que conta para o conjunto) serve de piloto observado** — é também o 1º teste do caminho concorrente contra a API real. Rode-o com `python3 script/gerar_lotes.py --limite 1`, confira a lista "O que conferir no piloto" abaixo (tempo, export, completação por construção, descartes, artefatos, custo real no painel), e só então siga. Os três passos originais ficam como referência histórica:

1. **Piloto de 10 itens com a string E1-M-A.** Confira tempo por item, exportação, contexto registrado, descartes e custo (itens abaixo).
2. **Smoke dos eixos E2 a E5**, cerca de 10 itens por eixo, para ver se cada eixo gera itens utilizáveis com o Sonnet 4.6.
3. **Um lote de 16 em E1-D-A (E1, Difícil, cenário A)**, o caso em que todos os modelos mais perderam na comparação. Critérios de aceitação: menos de 15 minutos, nenhuma duplicata no lote e checkpoint funcionando (retomar após interromper sem repetir nem perder itens).

Depois desses três passos, pare e confira os números com o orientador antes de iniciar a primeira sessão completa.

O que conferir no piloto:

- **Tempo por item.** Multiplique o tempo médio por 1.130 gerações (960 itens mais as refações esperadas) para planejar as sessões. Na comparação, o Sonnet 4.6 levou cerca de 124 s por item em série.
- **Exportação.** O arquivo traz identificador e contexto do lote, nível pedido, ficha, pistas com trecho e posição, `premise_alignment`, `difficulty_estimated` e `cues_completadas_por_construcao`.
- **Completação por construção.** Confirme que o valor é maior que zero nos itens com pista de domínio ausente; na comparação foi sempre zero.
- **Contexto registrado.** O modo Lote grava a string usada. O modo Único não grava e não é usado.
- **Descartes.** Quantos itens foram descartados, em cada uma das quatro categorias da seção 8.
- **Artefatos visíveis.** Procure links `.example`, `example.com`, porta `:0` e colchetes de placeholder nos itens aceitos.
- **Custo.** Custo por item, para fechar o orçamento.

Se algum desses pontos falhar, pare e resolva com o orientador antes de seguir.

## 7. As 60 strings de contexto

Estas strings não mudaram da v3. Cada célula tem quatro cenários (A a D). O cenário A é o da v1; B, C e D são novos, no mesmo grau de detalhe de cada nível. Cada lote usa um cenário, na ordem A, B, C, D. Cole a string no campo Contexto, exatamente como está. Cada string rende 16 exemplos.

Código da string: eixo-nível-cenário, por exemplo E1-D-C é o eixo 1, difícil, cenário C. Anote esse código no registro de lotes.

### E1 · Institucional acadêmico

Pistas que o eixo favorece: autoridade, urgência, escassez, domínio divergente.

| Cenário | Fácil | Médio | Difícil |
| --- | --- | --- | --- |
| A · Matrícula | E-mail institucional de uma universidade informando que há uma pendência registrada no sistema de matrícula. | Estudante de graduação de uma universidade pública brasileira recebe, no e-mail acadêmico, um aviso de que há uma pendência registrada em seu nome no sistema de matrícula e de que precisa regularizá-la junto à secretaria. | Estudante de graduação de uma universidade pública federal brasileira, na última semana do período de renovação de matrícula do semestre, recebe um aviso de que uma pendência de documentação no sistema acadêmico vai bloquear a renovação das disciplinas e de que precisa acessar o portal do aluno para regularizar a situação antes do fechamento do prazo, sob risco de perder as turmas já escolhidas. |
| B · Biblioteca | E-mail da biblioteca de uma universidade sobre uma pendência de material em atraso. | Estudante de graduação de uma universidade pública brasileira recebe um aviso da biblioteca de que consta uma devolução de material em atraso em seu nome e de que a pendência precisa ser quitada. | Estudante concluinte de uma universidade pública federal brasileira, às vésperas da colação de grau, recebe um aviso de que uma pendência de material em atraso na biblioteca vai bloquear a emissão do diploma e de que precisa quitar a devolução ou pagar a multa pelo sistema da biblioteca em até 48 horas, antes do fechamento da lista de formandos. |
| C · Bolsa | E-mail de uma universidade sobre o recadastramento anual de uma bolsa. | Bolsista de graduação de uma universidade pública brasileira recebe um aviso de que o cadastro da sua bolsa precisa ser atualizado junto à pró-reitoria de assuntos estudantis. | Bolsista de graduação de uma universidade pública federal brasileira recebe, nos primeiros dias do mês de pagamento, um aviso de que o recadastramento anual do auxílio permanência não foi concluído e de que precisa reenviar os comprovantes pelo sistema de bolsas até o dia seguinte, sob pena de o depósito do mês ser suspenso. |
| D · Colação | E-mail de uma universidade sobre a conferência de dados do histórico escolar. | Estudante concluinte de uma universidade pública brasileira recebe um aviso de que os dados do seu histórico escolar precisam ser conferidos e validados junto à secretaria acadêmica. | Estudante concluinte de uma universidade pública federal brasileira, na semana da cerimônia de colação, recebe um aviso de que uma divergência entre o histórico e os registros da secretaria impede a emissão do documento de conclusão e de que precisa confirmar os dados pelo portal acadêmico antes do fechamento da ata de colação. |

### E2 · Financeiro e Pix

Pistas que o eixo favorece: autoridade, pedido de credencial, typosquat, urgência.

| Cenário | Fácil | Médio | Difícil |
| --- | --- | --- | --- |
| A · Pix | E-mail de um banco sobre a atualização do cadastro da conta. | Correntista de um banco brasileiro recebe um aviso de que precisa reconfirmar os dados cadastrais da conta para manter o acesso aos serviços. | Correntista de um banco brasileiro que usa Pix com frequência recebe, no mesmo dia de uma transferência, um aviso de que a chave Pix cadastrada divergiu dos dados da conta e de que a reconfirmação do cadastro precisa ser feita pelo aplicativo no mesmo dia, sob risco de as transferências por Pix serem suspensas. |
| B · Cartão | E-mail de um banco sobre uma compra registrada no cartão de crédito. | Cliente de um banco brasileiro recebe um aviso de que uma compra não reconhecida foi registrada no cartão de crédito e de que precisa confirmar se a transação é sua. | Cliente de um banco brasileiro recebe, poucos minutos após uma compra, um aviso de que uma transação de valor elevado no cartão de crédito foi retida por suspeita de fraude e de que precisa confirmar os dados do cartão em até uma hora para liberar a compra e evitar o bloqueio preventivo. |
| C · Fatura | E-mail de um banco sobre a fatura do cartão de crédito. | Cliente de um banco brasileiro recebe um aviso de que a fatura do cartão de crédito está disponível e de que há um ponto a regularizar no pagamento. | Cliente de um banco brasileiro recebe, na data de vencimento da fatura, um aviso de que o pagamento do cartão não foi identificado e de que a regularização pelo link no mesmo dia evita juros e a inclusão do nome em cadastro de inadimplentes. |
| D · Rendimento | E-mail de um banco sobre a conta de investimentos. | Cliente de um banco brasileiro recebe um aviso de que os dados da conta de investimentos precisam ser atualizados para liberar movimentações. | Cliente de um banco brasileiro recebe, no dia do crédito dos rendimentos, um aviso de que uma pendência cadastral está retendo o resgate da aplicação e de que a atualização dos dados pelo aplicativo precisa ser concluída antes do fim do dia para liberar o valor. |

### E3 · Credenciais de TI e nuvem

Pistas que o eixo favorece: pedido de credencial, texto de link divergente, homoglifo.

| Cenário | Fácil | Médio | Difícil |
| --- | --- | --- | --- |
| A · Senha | E-mail do setor de TI sobre a senha do e-mail institucional. | Servidor de uma universidade pública brasileira recebe um aviso do setor de TI de que a senha do e-mail institucional está prestes a expirar e precisa ser renovada. | Servidor de uma universidade pública brasileira recebe, em nome da equipe de TI da instituição, um aviso de que a senha do e-mail institucional expira em 24 horas e de que a caixa atingiu a cota de armazenamento, com instrução para revalidar o acesso pelo portal de webmail antes do bloqueio da conta. |
| B · Armazenamento | E-mail do setor de TI sobre o espaço de armazenamento na nuvem institucional. | Servidor de uma universidade pública brasileira recebe um aviso do setor de TI de que o armazenamento na nuvem institucional está quase cheio e de que precisa liberar espaço para continuar recebendo e-mails. | Servidor de uma universidade pública brasileira recebe, em nome da equipe de TI, um aviso de que a cota de nuvem institucional foi atingida e de que novas mensagens serão recusadas até que o acesso seja revalidado pelo portal, com prazo de 24 horas antes da suspensão da caixa. |
| C · Autenticação | E-mail do setor de TI sobre a verificação em duas etapas do e-mail institucional. | Servidor de uma universidade pública brasileira recebe um aviso do setor de TI de que a verificação em duas etapas do e-mail institucional precisa ser reconfigurada. | Servidor de uma universidade pública brasileira recebe, em nome da equipe de TI, um aviso de que a verificação em duas etapas será desativada por inatividade e de que precisa reconfigurar o acesso pelo portal institucional em 24 horas para não perder o acesso ao e-mail. |
| D · VPN | E-mail do setor de TI sobre o acesso remoto à rede da instituição. | Servidor de uma universidade pública brasileira recebe um aviso do setor de TI de que o acesso remoto à rede da instituição precisa ser revalidado. | Servidor de uma universidade pública brasileira recebe, em nome da equipe de TI, um aviso de que o acesso remoto à rede foi suspenso após uma falha de segurança e de que precisa revalidar as credenciais pelo portal institucional antes do fim do expediente para voltar a acessar os sistemas internos. |

### E4 · Logística e cobrança de taxa

Pistas que o eixo favorece: urgência, anexo inesperado, domínio divergente.

| Cenário | Fácil | Médio | Difícil |
| --- | --- | --- | --- |
| A · Alfândega | E-mail sobre a entrega de uma encomenda. | Consumidor brasileiro que aguarda uma encomenda recebe um aviso de que o pacote está retido e de que há uma providência a tomar para liberá-lo. | Consumidor brasileiro que aguarda uma encomenda internacional recebe um aviso de que o pacote está retido na alfândega, com um valor de taxa a pagar pelo link informado e um prazo após o qual a encomenda será devolvida ao remetente. |
| B · Endereço | E-mail sobre os dados de entrega de uma encomenda. | Consumidor brasileiro que aguarda uma encomenda recebe um aviso de que o endereço de entrega está incompleto e de que precisa confirmar os dados para o pacote seguir. | Consumidor brasileiro que aguarda uma encomenda recebe um aviso de que a entrega falhou por endereço incompleto e de que precisa confirmar os dados pelo link em até 24 horas, ou o pacote retornará ao centro de distribuição e a reentrega terá custo. |
| C · Reentrega | E-mail sobre uma nova tentativa de entrega de uma encomenda. | Consumidor brasileiro que aguarda uma encomenda recebe um aviso de que houve uma tentativa de entrega sem sucesso e de que precisa reagendar o recebimento. | Consumidor brasileiro que aguarda uma encomenda recebe um aviso de que a segunda tentativa de entrega falhou e de que uma taxa de reenvio precisa ser paga pelo link em 48 horas, sob pena de o pacote ser devolvido ao remetente. |
| D · Tributo | E-mail sobre uma taxa referente a uma compra. | Consumidor brasileiro que fez uma compra on-line recebe um aviso de que há um tributo pendente sobre o pedido e de que precisa quitá-lo para a liberação. | Consumidor brasileiro que comprou de uma loja no exterior recebe um aviso de que o pedido só será liberado após o pagamento de um tributo de importação, com um boleto em anexo e um prazo de dois dias antes do cancelamento automático da compra. |

### E5 · Seleção e oportunidade

Pistas que o eixo favorece: escassez, saudação genérica, anexo inesperado.

| Cenário | Fácil | Médio | Difícil |
| --- | --- | --- | --- |
| A · Estágio | E-mail sobre uma vaga de estágio. | Estudante universitário brasileiro inscrito em um processo seletivo de estágio recebe o resultado da seleção. | Estudante universitário brasileiro que se inscreveu em um processo seletivo de estágio recebe o resultado informando a aprovação, com um documento de confirmação em anexo e um prazo curto para aceitar a vaga antes que ela seja repassada ao próximo colocado. |
| B · Entrevista | E-mail sobre uma entrevista de um processo seletivo. | Estudante universitário brasileiro inscrito em um processo seletivo recebe um convite para uma entrevista. | Estudante universitário brasileiro inscrito em um processo seletivo de estágio recebe um convite para entrevista com data e horário marcados, um formulário em anexo para preencher antes e um prazo curto para confirmar a presença, sob risco de perder a vaga. |
| C · Bolsa | E-mail sobre um programa de bolsas. | Estudante universitário brasileiro recebe um aviso sobre uma vaga em um programa de bolsas. | Estudante universitário brasileiro que demonstrou interesse em um programa de bolsas recebe um aviso de que foi pré-selecionado, com um termo de adesão em anexo e poucas vagas remanescentes a confirmar até o dia seguinte. |
| D · Emprego | E-mail sobre uma oportunidade em um programa de trainee. | Estudante universitário brasileiro recebe uma oferta para participar de um programa de trainee. | Estudante universitário brasileiro em fim de curso recebe uma oferta para um programa de trainee informando a aprovação em uma etapa, com um contrato em anexo e um prazo curto para aceitar antes que a vaga seja repassada a outro candidato. |

## 8. Plano de lotes, execução e registro

Cada célula sai de 4 lotes de 16, um por cenário. Como cada nível tem a sua própria string, um lote recebe um contexto e um nível: o modo Lote divide o contexto entre as dificuldades marcadas, então marque uma só, a do contexto colado.

Quatro lotes por célula, e não dois de 50, porque a recuperação na base de artigos roda uma vez por lote e todos os itens do lote compartilham o mesmo contexto recuperado. Quatro lotes dão quatro sorteios independentes por célula, o que reduz o risco de a célula herdar a idiossincrasia de um sorteio só.

| Parâmetro | Valor |
| --- | --- |
| Modo de geração | Lote, sempre |
| Dificuldades marcadas | Uma só, a do contexto colado |
| Gerar phishing | Marcado |
| Itens por lote | 16 (emenda v3.1.1) |
| Lotes por célula | 4 (cenários A, B, C, D) |
| Lotes no total | 60 (15 células × 4), mais lotes extras para completar células curtas |
| Itens no total | 960 utilizáveis (meta ajustada ao orçamento) |

### Ordem de execução

**Ordem por rodada de cenário (emenda v3.1.1, substitui "um eixo por sessão").** O driver (`script/gerar_lotes.py`) roda **todas as 15 células no cenário A, depois B, C e D**, com os níveis intercalados dentro de cada rodada. Assim, se o crédito acabar no meio, o conjunto fica **equilibrado** (faltam cenários, não eixos inteiros) — em vez de "um eixo por sessão", que deixaria eixos inteiros faltando. Isto é um **desvio registrado** do desenho original. Ao fim de cada rodada, confira a cobertura de pistas (seção 9) para planejar lotes extras.

### Registro por lote

Mantenha uma planilha com uma linha por lote. É o que garante a reprodutibilidade e responde às perguntas que um avaliador faz.

| Coluna | Exemplo |
| --- | --- |
| lote\_id | E1-F-A-01 |
| eixo | E1 |
| nivel\_pedido | Fácil |
| cenario | A |
| string\_contexto | (a string colada, igual à seção 7) |
| modelo | identificador exato do Sonnet 4.6 no Console |
| temperatura | padrão do modelo |
| saida\_estruturada | instructor ANTHROPIC\_JSON |
| versao\_app | hash do commit (`git_commit` do metadata) |
| semente | semente do sorteio das fichas |
| data\_hora | 2026-11-03 14:30 |
| itens\_pedidos | 25 |
| itens\_utilizaveis | 22 |
| descartes\_duplicata | 1 |
| descartes\_recusa | 2 |
| descartes\_validacao | 0 |
| descartes\_infra | 0 |
| arquivo\_export | E1\_2026-11-03.csv |
| observacoes | erros, reexecuções |

### Categorias de descarte

A conta dos 64 por célula só fecha se cada item fora do conjunto tiver motivo registrado:

- **Duplicata:** quase-duplicado dentro do lote, pelo limiar da aplicação.
- **Recusa ou neutralização:** recusa explícita, disclaimer na mensagem ou recusa branda (seção 5).
- **Erro de validação:** falha de formato ou de regra (por exemplo remetente sem e-mail, link inválido, pista sem evidência válida) que persistiu após as regenerações do pipeline.
- **Erro de infraestrutura:** falha de rede, de taxa ou de gravação; o item é refeito sem contar como falha do modelo.

Confira no E1 e no nível Difícil, onde a perda esperada é maior, e rode lotes adicionais com o mesmo cenário até a célula chegar a 64 itens utilizáveis.

### Exportação e backup

- **Exporte ao longo do caminho,** não só no fim. A exportação sobrescreve os arquivos anteriores; guarde cada retrato com a data no nome antes de rodar de novo.
- **Preserve as colunas de lote.** O identificador e o contexto do lote amarram cada exemplo à sua célula. Sem eles, não há como analisar por contexto.
- **Backup do banco ao fim de cada sessão.** Faça uma cópia do banco, e não apenas "não derrubar os volumes": parar e retomar preserva os exemplos, mas remover os volumes apaga tudo.
- **Interrupção.** Se a geração parar no meio de um lote (crédito esgotado, falha de rede), retome pelo checkpoint e anote a interrupção em `observacoes`. Confira o saldo de crédito antes de cada sessão.

### Acompanhamento

Marque conforme concluir. Cada item é um lote de 16.

- [ ] E1 · Institucional acadêmico: F-A, F-B, F-C, F-D, M-A, M-B, M-C, M-D, D-A, D-B, D-C, D-D
- [ ] E2 · Financeiro e Pix: F-A, F-B, F-C, F-D, M-A, M-B, M-C, M-D, D-A, D-B, D-C, D-D
- [ ] E3 · Credenciais de TI e nuvem: F-A, F-B, F-C, F-D, M-A, M-B, M-C, M-D, D-A, D-B, D-C, D-D
- [ ] E4 · Logística e cobrança de taxa: F-A, F-B, F-C, F-D, M-A, M-B, M-C, M-D, D-A, D-B, D-C, D-D
- [ ] E5 · Seleção e oportunidade: F-A, F-B, F-C, F-D, M-A, M-B, M-C, M-D, D-A, D-B, D-C, D-D

## 9. Controle de qualidade do conjunto gerado

Depois de exportar tudo, antes de levar aos especialistas, rode estas conferências sobre os 960 itens e guarde os resultados.

1. **Contagem por célula.** Confirme quantos itens utilizáveis cada célula tem depois dos descartes, por categoria (seção 8). Complete as que ficaram curtas, com atenção ao E1 e ao nível Difícil.
2. **Deduplicação global.** O descarte de quase-duplicados da aplicação acontece só dentro de um lote, e o limiar é alto. Rode uma deduplicação entre todos os 960, com método e limiar escritos (por exemplo, similaridade de cosseno maior ou igual a 0,95 sobre o embedding do corpo). Relate quantos itens saíram por célula. Confira também a repetição de assunto, que na comparação chegou a 32% das tentativas.
3. **Diversidade interna.** Meça a similaridade média entre pares dentro de cada célula. Cem exemplos de um mesmo contexto tendem a repetir estrutura, e o leitor precisa conhecer isso. Relate o valor por célula.
4. **Cobertura de pistas.** Conte quantas vezes cada um dos dez códigos aparece no conjunto, separando pistas de corpo e pistas de domínio, e quantas foram completadas por construção. Códigos raros, como homoglifo e anexo inesperado, podem não aparecer o suficiente para estimar precisão; com 960 itens, cada código aparece bem menos vezes que na v2 (3.000 itens), e o homoglifo em especial é só-LLM (emenda v3.1.1), então pode não dar para estimar precisão para ele. Faça essa contagem também ao fim de cada sessão, para gerar lotes extras enquanto o eixo ainda está em andamento. Se algum ficar escasso, gere lotes extras nos eixos que o favorecem (seção 3).
5. **Marcas reais.** As strings não citam marcas, mas o modelo pode inventar nomes reais, como Correios, Receita, bancos ou a UFPA. Procure esses nomes no conjunto. Combine com o orientador se serão mantidos, substituídos por nomes fictícios ou removidos. Faça o mesmo para dados que pareçam pessoais, como nomes e CPFs.
6. **Artefatos visíveis ao especialista.** Procure, nos campos que o especialista vê (e-mail, assunto, remetente e links), domínios reservados (`.example`, `example.com`, `.test`, `.invalid`), porta `:0`, placeholders entre colchetes (`[LINK]`, `[SEU NOME]`), links genéricos (por exemplo `suauniversidade`, `outrodominio`), `\n` literal e frases que narrem a simulação ("exemplo educativo", "simulação"). Itens com artefato são regenerados ou excluídos antes da amostragem.
7. **Fidelidade à ficha.** Confira, por amostragem, se o remetente e o domínio do link seguem a ficha sorteada, e relate a taxa de itens em que não seguem.
8. **Posições zeradas.** A aplicação confere, em cada pista, se o trecho de evidência corresponde à posição indicada, e zera a posição quando não corresponde. A taxa de posições zeradas nos 960 é um indicador de confiabilidade do anotador automático, obtido sem gastar hora de especialista. Ressalva: ele mede se o trecho citado existe no e-mail, não se o código da pista está certo.
9. **Itens sem pista.** Nenhum item com `cue_count = 0` e dificuldade "difícil" pode seguir; é sinal de recusa branda que passou pelo detector.

## 10. A amostra que os especialistas anotam

Os 960 exemplos não vão todos para anotação humana. A validação se faz sobre uma subamostra estratificada de 300 a 350 itens.

### Como selecionar

- Estratifique pela saída da aplicação, cruzando `difficulty_estimated` com `premise_alignment`, e não pelo nível pedido. Estratificar pelo nível pedido pode deixar uma classe de saída com zero casos, e aí não há como estimar precisão para ela.
- Cerca de 30 itens por célula observada (3 dificuldades × 3 classes de alinhamento), o que dá em torno de 270 itens. Se uma célula observada tiver menos de 30 itens no conjunto, entram todos; com 960 itens, isso é mais provável nas combinações raras.
- 20% dos itens anotados por dois especialistas, para calcular a concordância entre avaliadores.
- Só itens utilizáveis e sem artefato visível entram na amostragem (seções 5 e 9).
- Os dois especialistas da dupla não incluem quem gerou os exemplos.

### O que o especialista vê

O especialista vê apenas o e-mail, o assunto, o remetente e os links de cada item, em ordem aleatória. Ele nunca vê a `explicacao`, o nível pedido, a ficha, o contexto da requisição (exceto ao julgar o alinhamento, quando lê a string de contexto) nem os rótulos da aplicação. As pistas de domínio são avaliáveis pelo remetente e pelos links; se o orientador decidir ocultar o domínio oficial, essas pistas saem da medida de revocação e devem ser reportadas à parte.

### Como anotar

- **Às cegas.** O especialista anota sem ver os rótulos da aplicação nem o nível pedido. Se vir as pistas do LLM, a revocação não pode ser medida e a precisão fica inflada.
- **Manual de anotação.** Escreva um manual com a definição dos dez códigos de pista da taxonomia (seção 3) e das três classes de alinhamento, com um exemplo de cada. O especialista anota apenas esses dez códigos. Erro gramatical e remetente suspeito são sinais de estilo do nível fácil, não códigos da taxonomia, e a aplicação não os emite.
- **Piloto de calibração.** Antes da anotação oficial, os dois especialistas anotam os mesmos cerca de 20 itens, comparam e ajustam o entendimento do manual. Esses 20 não entram no cálculo final.
- **Ordem aleatória.** Embaralhe os itens, para que eixo e nível não apareçam em blocos.

### O que calcular

| Rótulo | Métrica | Observação |
| --- | --- | --- |
| Pistas de corpo | Precisão e revocação por código | Reporte intervalo de confiança; códigos raros têm intervalo largo |
| Pistas de domínio | Precisão e revocação por código, à parte | Medem a regra de completação e a ficha, não só o LLM (seção 2) |
| Alinhamento | Concordância de três classes | Kappa ponderado entre LLM e especialista |
| Dificuldade | A regra corta onde o humano corta? | Aplique a regra às anotações humanas e compare com a dificuldade percebida |
| Entre avaliadores | Kappa de Cohen | Sobre os 20% com dupla anotação |

- **Pondere pelos estratos.** Como a amostra é estratificada, qualquer número geral (uma precisão média, por exemplo) precisa ser ponderado pelo peso de cada estrato nos 960. Sem isso, estratos pequenos pesam demais.
- **Trate o lote como grupo.** Os 16 itens de um lote compartilham o contexto recuperado, logo não são totalmente independentes. Nos intervalos de confiança, use o lote como unidade de agrupamento.
- **Declare a cobertura.** Os itens perdidos para recusa ou neutralização se concentram em E1 e Difícil; reporte o rendimento por célula junto com a precisão, para que o leitor saiba o que o conjunto não cobre.

## 11. Blocos opcionais, uso posterior, ética e entrega

### Blocos opcionais

Dois blocos fortalecem o trabalho e só rodam se houver tempo e orçamento. Combine com o orientador antes.

- **Bloco A · E-mails legítimos pareados.** Se algum trabalho do ecossistema for classificar phishing contra legítimo, os 960 exemplos não bastam: são todos phishing. Um classificador treinado com phishing gerado de um lado e legítimos de outra fonte aprende a diferença de origem, não a de phishing. Para evitar isso, gere e-mails legítimos nos mesmos cinco eixos e contextos, desmarcando a opção de gerar phishing. A comparação de modelos só testou geração maliciosa, então este bloco precisa de um smoke próprio com o Sonnet 4.6 antes de rodar.
- **Bloco B · Fatorial de detalhe × nível pedido.** O nível é movido por três alavancas ao mesmo tempo: a instrução de nível, o detalhe do contexto e a ficha. Para separar o efeito delas, rode, em um eixo, um pequeno fatorial: 3 graus de detalhe × 3 níveis pedidos, com cerca de 30 itens por combinação. Isso mostra se a dificuldade estimada responde mais ao prompt ou ao contexto.

### Uso posterior dos dados

Esta seção não faz parte da geração. São as regras mínimas para que outro trabalho do ecossistema, como um classificador, reutilize o conjunto sem inflar o resultado.

- **Divida por grupo, nunca ao acaso.** Itens do mesmo lote compartilham contexto recuperado, e itens do mesmo cenário compartilham vocabulário. Uma divisão aleatória coloca itens parecidos no treino e no teste ao mesmo tempo e infla a acurácia. Deixe cenários ou eixos inteiros fora do treino.
- **Separe rótulo prata de rótulo ouro.** O rótulo da aplicação (prata) serve de treino; o rótulo do especialista (ouro) é o único válido para o teste. Treinar e testar nos rótulos da aplicação só ensina o classificador a imitar a regra.
- **Não misture versões da aplicação nem modelos.** Se a aplicação ou o modelo mudar e novos exemplos forem gerados, anote o commit e o identificador do modelo e não junte com os antigos sem registrar a diferença. O Sonnet 4.6 tem disponibilidade garantida apenas até 17/02/2027, o que limita a reprodução exata da geração depois dessa data; declare isso como limitação.
- Como cada item carrega eixo, nível, cenário, lote e ficha (seção 8), todas essas divisões são possíveis depois, sem gerar de novo.

### Ética e segurança

O conjunto é formado por e-mails de phishing realistas, logo é material de uso dual e exige cuidado.

- **Cobertura ética.** Confirme com o orientador se a geração, o uso pelo aluno e a anotação estão cobertos pelo protocolo aprovado no CEP-ICS/UFPA. Se o aluno da graduação não estiver listado, verifique se precisa constar.
- **Acesso restrito.** Guarde o conjunto em local de acesso restrito à equipe do projeto. Não publique os exemplos brutos sem combinar antes.
- **Marcas e dados pessoais.** Siga o item 5 da seção 9: nomes de marcas reais e dados que pareçam pessoais são sinalizados e tratados antes de o conjunto circular.
- **Fornecedor do modelo.** As requisições de geração vão à API da Anthropic. Confirme com o orientador que isso está compatível com a política de uso do fornecedor para pesquisa e com o protocolo ético, e registre a finalidade junto aos dados.
- **Finalidade.** O conjunto é para pesquisa e treinamento de conscientização. Registre essa finalidade junto aos dados.

### Checklist de entrega

- [ ] Taxonomia confirmada, modelo confirmado e versão da aplicação congelada (commit e identificador do modelo anotados).
- [ ] Cenários B, C e D aprovados pelo orientador.
- [ ] 1º lote real (16 itens) rodado como piloto observado (emenda v3.1.1, decisão 1 — smokes pagos cancelados), com os critérios da seção 6 conferidos.
- [ ] 60 lotes de 16 gerados (mais os extras), com a planilha de registro preenchida e os descartes por categoria.
- [ ] Exportações datadas e backup do banco por sessão.
- [ ] Contagem, deduplicação, diversidade, cobertura de pistas e fidelidade à ficha calculadas.
- [ ] Marcas reais, dados pessoais e artefatos visíveis verificados.
- [ ] Taxa de posições zeradas calculada sobre os 960.
- [ ] Subamostra estratificada selecionada pela saída da aplicação.
- [ ] Manual de anotação e piloto de calibração prontos.
- [ ] Cobertura ética confirmada e conjunto em local restrito.

PhishForge · protocolo de geração para validação de ground truth · v3.1.
