# Identidade da organização e domínios de pista na geração (piloto 5)

Este documento descreve **o que o gerador faz hoje** depois das correções de
qualidade do piloto 5 (itens 2.1 a 2.6 da proposta revisada contra o
Protocolo de geração v2). Ele não repete o protocolo: o protocolo é quem
decide o que o estudo exige (eixos, níveis, pistas-alvo, curadoria de marca
real); este documento é só o "como" o código atende a isso. Se os dois
divergirem, o protocolo manda — e é sinal de que este arquivo ficou
desatualizado.

Fora de escopo aqui, de propósito (ver `docs/` do piloto 4 e a ata de decisão
com o orientador quando existir):

- A alavanca do alinhamento de premissa no nível fácil (seção 3 da proposta
  de 28/10): é decisão de desenho do protocolo, não mudança de código.
- As definições de anotação de `generic_greeting` em comunicação em massa e
  de `link_text_mismatch` em texto de link genérico: são decisão do manual
  de anotação, compartilhada entre o gerador, o anotador às cegas e o
  especialista — não algo que só o código possa fixar sozinho.

## 1. Diagnóstico (por que isto existe)

No piloto 4, 22 das 25 falhas de geração vinham da mesma causa: a regra de
forma mandava o LLM "inventar um nome fictício e plausível", repetindo a
palavra "fictícia/o" três vezes no mesmo prompt. O modelo levava a
instrução ao pé da letra e escrevia literalmente "Universidade Fictícia"; o
validador pós-geração barra esse literal e manda gerar de novo — **com a
mesma instrução**, então o modelo reincidia. O mesmo problema de fundo
("pedir ao LLM para inventar algo que o código já poderia fornecer")
aparecia em mais dois pontos: o domínio de typosquat/sender_domain_mismatch
saía inconsistente (1 em 4 itens que pediam typosquat de fato o tinham), e
o endereço do destinatário virava um placeholder
(`aluno@universidadeficticia.com`, 17 dos 27 e-mails fáceis salvos).

A correção comum aos itens 2.1–2.3 é: **o código fornece o dado pronto na
ficha; o LLM só usa.**

## 2.1 — Identidade da organização vem da ficha, não do LLM

- `app/domain/models/instituicao_ficticia.py`: `InstituicaoFicticia` —
  `nome_base`, `sigla`, `dominio_oficial`.
- `app/domain/services/instituicoes_ficticias.py`: lista versionada de 20
  identidades (análoga a `instituicoes_reais.py`, mas na direção oposta) —
  variedade suficiente para o ciclo balanceado não repetir a mesma
  instituição cedo demais dentro de um lote grande do protocolo.
  Cada entrada é conferida (`tests/unit/test_variation_sampler.py::test_nenhuma_instituicao_ficticia_dispara_os_proprios_detectores`)
  contra os próprios detectores de instituição real, domínio caricato e
  marcador — senão a identidade recém-criada se bloquearia sozinha.
- `nome_base` é **deliberadamente sem palavra de categoria** ("Vallonta",
  não "Universidade Vallonta" nem "Banco Vallonta"): o `VariationSampler` é
  genérico entre os 5 eixos do protocolo e não sabe se o cenário pedido é
  universidade, banco, órgão público, varejo ou telecom. O LLM, que já
  recebe o cenário no prompt, é quem compõe o nome de categoria com o
  nome-base — essa é a única coisa que o código ainda delega a ele.
- Sorteio: `VariationSampler.sortear()` tira uma instituição por item, em
  ciclo balanceado como as demais dimensões da ficha (nenhuma repete antes
  de esgotar a lista). Para a planilha do protocolo fixar a instituição de
  uma célula inteira, `BatchGenerationRequest.instituicao` (campo opcional
  de `POST /api/v1/generate/batch`) passa a identidade pronta; o
  `VariationSampler` recebida ela no construtor e para de sortear.
- A regra de forma do prompt (`_REGRAS_DE_FORMA` em
  `response_generator.py`) não pede mais para "inventar" nada: instrui a
  usar nome-base, sigla e domínio exatamente como vêm na ficha, e proíbe
  nome/sigla/domínio de instituição real em qualquer lugar do e-mail —
  mesmo que o cenário cite uma.

## 2.2 — Domínios de pista calculados pelo código

- `typosquat`: `variation_sampler.gerar_typosquat(dominio_oficial, rng)`
  parte do domínio oficial da ficha e aplica, no primeiro rótulo (antes do
  primeiro ponto), uma de quatro mutações de distância de edição 1: trocar
  um caractere por um vizinho visual (`o↔0`, `l↔1`, `i↔1`, `e↔3`, `a↔4`,
  `s↔5`, `b↔6`, `g↔9`, `t↔7`, `u↔v`, `n↔m`), duplicar, remover ou inserir
  um caractere. O domínio exato entra na ficha (`VariationSpec
  .dominio_da_pista`); o LLM só copia. Essa é agora a definição operacional
  de `typosquat` neste gerador — a mesma que deveria ir para o manual de
  anotação, para o LLM e o especialista julgarem com o mesmo critério.
- `sender_domain_mismatch`: `variation_sampler._dominio_mismatch()` sorteia
  um webmail gratuito (`gmail.com`, `outlook.com`, `hotmail.com`) em
  fácil/médio, ou o domínio oficial de **outra** instituição da lista em
  difícil (plausível, de terceiros, mas sem erro de digitação — para não
  colidir com a definição de `typosquat`).
- `VariationSpec.dominio_da_pista_em` diz onde o domínio literal deve
  aparecer (`"remetente"`, `"link"` ou `"remetente_e_link"`), porque no
  nível difícil o typosquat vai no link obrigatório (o orçamento de 1
  pista já está consumido por ele) enquanto o sender_domain_mismatch vai
  nos dois — o mesmo endereço no remetente e no destino do link.

## 2.3 — Endereço do destinatário calculado pelo código

- `VariationSpec.endereco_destinatario`: endereço de e-mail literal,
  montado por `variation_sampler._endereco_destinatario()`. Com nome
  (médio/difícil), a parte local é o nome sem acento e em minúsculas,
  separado por ponto (`"Larissa Monteiro"` → `larissa.monteiro`). Sem nome
  (fácil, saudação genérica), é um contato numerado (`contatoNNN`) — nunca
  um placeholder como "aluno" sozinho.
- O domínio do endereço é sorteado por item (ciclo balanceado,
  `destinatario_dominio_tipo`), entre o domínio oficial da própria
  organização (destinatário "de dentro", ex.: aluno com e-mail
  institucional) ou um webmail pessoal (destinatário externo).
- A regra de forma passa a exigir que `receptor` use **exatamente** o
  endereço da ficha, nunca um endereço inventado pelo LLM.

## 2.4 — Rendimento e viés de seleção

`GET /api/v1/generate/batch/{job_id}` agora devolve, além do que já existia:

- `taxa_aproveitamento`: `total_generated / total_requested`. Já era
  calculável a partir dos outros campos, mas precisava ser derivado à mão
  a cada análise.
- `regeneracoes_por_motivo`: soma, por motivo (`marcador`, `remetente`,
  `destinatario`, `instituicao_real`, `dominio_caricato`, `assunto`),
  quantas vezes os itens **aceitos** deste lote precisaram ser gerados de
  novo. É a taxa de bloqueio de cada validação — em particular, a de
  `instituicao_real`, que o refinamento da seção 3 deste documento deveria
  ter reduzido bastante com a 2.1 fornecendo a identidade pronta.

Nota de viés de seleção, para constar em qualquer análise destes números:
**os itens aceitos num lote não são amostra aleatória do que o LLM
produz** — são o que sobrou depois do filtro de qualidade. Uma
`difficulty_estimated` calculada só sobre os itens aceitos mede a
dificuldade desse subconjunto, não da distribuição que o LLM geraria sem
filtro nenhum.

Este item **não** mudou a política de completar célula curta do protocolo
(gerar lote adicional com o mesmo cenário) — só reduz a frequência com que
ela precisa ser acionada, ao atacar a causa mais comum de falha (2.1).

## 2.5 — Teto de tokens de saída

`ResponseGenerator` aceita `max_tokens_geracao` (default 2000) e
`max_tokens_anotacao` (default 1000), configuráveis por
`MAX_TOKENS_GERACAO`/`MAX_TOKENS_ANOTACAO` no `.env` (ver
`app/core/config.py`). Antes não havia teto nenhum: uma chamada que entrava
em repetição estourava o limite de contexto do modelo (16k tokens) e só
falhava depois de consumir a chamada inteira. Com o teto, a mesma falha
acontece mais cedo e mais barato. Aplicado à chain de geração de e-mail e
às cinco chains de canal (website, phone_call, pix_qr, sms, whatsapp); a
chain de anotação às cegas usa o teto menor; HyDE, fusão de contexto e
tradução não têm teto novo (saída livre, não structured output).

## 2.6 — Ajustes menores

- `"123456"` como sequência de dígitos ascendentes é tratado como marcador
  de template (`item_validation._NUMERO_MARCADOR`), no mesmo mecanismo que
  já trata `[Nome do Estudante]` ou `"Universidade Exemplo"` — um item com
  essa sequência é gerado de novo.
- O prompt de e-mail (malicioso e legítimo) recebe a data de hoje por
  extenso (`{data_atual}`, calculada em `response_generator
  ._data_atual_por_extenso()`, sem depender de locale do sistema). Antes o
  modelo não sabia que data era "hoje" e podia citar uma data do próprio
  treinamento já no passado.

## 3 — Bloqueio de instituição real: só em personificação

O bloqueio de instituição real (que manda gerar o item de novo quando acha
UFRJ, Banco do Brasil, `gov.br` etc.) disparava em **qualquer menção**,
inclusive dentro do corpo do e-mail em texto corrido — "entregue pelos
Correios" num cenário de logística acionava o bloqueio do mesmo jeito que
`@correios-br.com` no remetente, mesmo sendo os dois casos muito
diferentes: o primeiro é menção legítima dentro do pretexto, o segundo é
personificação de fato.

`item_validation.py` agora separa os dois critérios:

- `encontrar_dominios_reais`: um domínio real (`bb.com.br`, `receita.gov.br`)
  conta em **qualquer campo**, inclusive o corpo — escrever um domínio real
  é, por si, a forma de apontar para o endereço dele; não há "menção
  inocente" de domínio.
- `encontrar_nomes_de_instituicoes_reais`: um nome ou sigla (`UFRJ`,
  `Banco do Brasil`, `Correios`) só conta quando aparece em
  **remetente, destinatário ou links** — onde a identidade de quem
  envia/recebe/aponta é de fato reivindicada. Uma menção ao nome dentro do
  corpo, sem nenhuma personificação, deixa de bloquear.
- `encontrar_instituicoes_reais` (o critério antigo, combinando os dois sem
  distinguir campo) continua existindo para quem não tem essa distinção —
  hoje, só `limpar_contexto_fundido` (o resumo do RAG não tem "campos").
- `ResponseGenerator._problema_estrutural` é quem aplica a distinção na
  checagem pós-geração do item.

Com a 2.1 fornecendo a identidade fictícia pronta, o modelo quase não
precisa inventar nome de organização — então o bloqueio deveria disparar
bem menos que no piloto 4, mesmo sem o refinamento de campo. O refinamento
ataca o que sobra: o caso em que o modelo, ao elaborar o cenário em prosa,
cita de passagem uma instituição real que o cenário descreveu (ex.: um
cenário que menciona "a Receita Federal" como contexto, não como quem
envia o e-mail).

## Onde cada coisa está (referência rápida)

| O quê | Arquivo |
|---|---|
| Identidade fictícia (modelo + lista) | `app/domain/models/instituicao_ficticia.py`, `app/domain/services/instituicoes_ficticias.py` |
| Ficha de variação (campos novos) | `app/domain/models/variation_spec.py` |
| Sorteio da ficha, typosquat, domínio de destinatário | `app/domain/services/variation_sampler.py` |
| Regra de forma do prompt, data atual, teto de tokens | `app/domain/services/response_generator.py` |
| Bloqueio por personificação, marcador "123456" | `app/domain/services/item_validation.py` |
| Override de instituição por lote, teto de tokens (config) | `app/dto/requests.py`, `app/core/config.py`, `app/core/container.py` |
| Fio do override até o sampler, metadado do lote | `app/domain/services/batch_generation_worker.py` |
| `taxa_aproveitamento`, `regeneracoes_por_motivo` | `app/api/v1/endpoints/generator.py` (`GET /generate/batch/{job_id}`) |

## Testando

```bash
poetry run pytest tests/unit -v
```

Os testes relevantes a esta mudança:

- `tests/unit/test_variation_sampler.py` — sorteio e override de
  instituição, `gerar_typosquat`, domínio de destinatário.
- `tests/unit/test_item_validation.py` — marcador `"123456"`, separação
  nome/domínio de instituição real.
- `tests/unit/test_response_generator_ficha.py` — regra de forma sem
  "invente um nome fictício", bloqueio só em personificação,
  `{data_atual}` no prompt.
- `tests/unit/test_batch_worker_ficha.py` — override de instituição vale
  para o lote inteiro, registrado em `run_metadata`.
- `tests/unit/test_batch_job.py` — `taxa_aproveitamento`,
  `regeneracoes_por_motivo` e o override de instituição pela API.

Depois de um lote novo, confira `run_metadata.versao_gerador` — mudar
prompt ou validação muda `VERSAO_GERADOR` em `response_generator.py`, para
lotes de versões diferentes não se misturarem na análise do protocolo.
