# Recalibração de `difficulty_estimated` — proposta (sobre os 960, sem gerar nada)

**Para decisão do orientador.** Recálculo determinístico sobre os rótulos já
salvos (`cue_count` + `premise_alignment` de cada item). Nenhum exemplo foi
gerado; nenhum custo de API. Conjunto: 960 itens, commit `ac0e3a3`.

## O problema (verificado nos 960)

- **`difficulty_estimated` nunca sai "difícil":** a distribuição atual é
  **fácil 225 / médio 735 / difícil 0**.
- **Causa real** (corrigindo o diagnóstico que circulou): a regra **não** ignora
  o `cue_count`. Ela é `pontos_cue(cue≤1→2, ==2→1, ≥3→0) + pontos_alinhamento
  (alto→2, médio→1, baixo→0)`, e **difícil = soma 4 = `cue_count ≤1` E alto**.
  Só que **todo item tem ≥2 pistas** (distribuição real abaixo), então o termo de
  pistas é sempre 0 → soma máxima = 3 = médio. O corte de "difícil" (`≤1` pista)
  é **inatingível** dada a densidade de pistas do gerador. O próprio código marca
  os cortes como "candidatos a revisão quando houver dado de calibração".
- **Fator estrutural:** 77% dos itens têm alinhamento **alto** (ver abaixo) — por
  isso qualquer regra muito atrelada ao alinhamento infla o "difícil".

### Distribuições reais (os dois eixos da regra)

- **`cue_count`** (mín 2, máx 9, mediana 5, terços em 5/6):
  `{2:4, 3:63, 4:203, 5:291, 6:229, 7:123, 8:44, 9:3}`
- **`premise_alignment`:** `{baixo:14, médio:211, alto:735}`

## Opções de recalibração (distribuição resultante sobre os 960)

| Regra | fácil | médio | difícil | Comentário |
|---|---:|---:|---:|---|
| **Baseline (atual)** | 225 | 735 | **0** | sem "difícil" — o problema |
| A — terços de `cue` (≤5/6/≥7) + alinhamento | 72 | 418 | 470 | "difícil" pesado demais (49%) |
| B — matriz 2D (difícil = alto & `cue`≤5) | 143 | 347 | 470 | "difícil" pesado |
| C — só alinhamento (baixo/médio/alto → f/m/d) | 14 | 211 | 735 | "difícil" domina; ignora pistas |
| **D — estrutura atual, cortes `cue` ≤4/5/≥6** | 139 | 580 | **241** | **menor mudança; 3 classes** |
| **E — 2D, difícil = alto & `cue`≤4** | 143 | 576 | **241** | equivalente à D, formulação 2D |

### Recomendada: **Opção D** (menor mudança)

Mantém **a estrutura exata** da regra (soma de dois eixos; `≤1 fácil / 2–3 médio
/ 4 difícil`); só recalibra os cortes de `cue_count` de `≤1/==2/≥3` para
**`≤4/5/≥6`**, para caírem na faixa real do gerador. Resultado: **fácil 139 /
médio 580 / difícil 241**.

Cruzamento nível **pedido** × dificuldade **estimada** (Opção D):

| pedido \ estimada | fácil | médio | difícil |
|---|---:|---:|---:|
| fácil | 110 | 206 | 4 |
| médio | 20 | 197 | 103 |
| difícil | 9 | 177 | 134 |

## Ressalvas honestas (limites do que isto prova)

- **Bater com o nível *pedido* não é validação.** O protocolo (seção 4) diz que
  essa concordância é em parte embutida no desenho. **Quem valida o corte é o
  especialista** (a mesma regra aplicada às *anotações humanas* vs a dificuldade
  percebida — seção 2/10). A recalibração só garante que a amostra dos
  especialistas tenha **as três classes** para anotar.
- Escolher o corte **antes** de ver os dados dos especialistas é legítimo (não é
  p-hacking); escolher depois, olhando o resultado, não seria.
- O conjunto fica **médio-pesado** (≈60%) em qualquer opção balanceada, porque
  77% dos itens são de alinhamento alto — isso é característica do gerador e deve
  ser declarado.

## Observação relacionada: nível médio sem link (característica de desenho)

Os 320 itens do **médio não têm link** (fácil e difícil têm todos). **Não é bug:**
o pool de ações da ficha do nível médio é sem link ("abrir anexo", "responder o
e-mail", "ligar para um número"), enquanto fácil e difícil usam "acessar o link".
Consequência: pistas dependentes de link são estruturalmente ausentes no médio
(`link_text_mismatch`: fácil 243, **médio 0**, difícil 260). **Recomendação (sem
budget para regerar):** declarar como característica de desenho e, no médio, medir
precisão/revocação **só dos cues que não dependem de link**.

## Se o Renato aprovar uma regra

É só dizer qual (D, E, ou outros cortes) que eu **gero o arquivo dos 960 com o
`difficulty_estimated` recalculado** (campo novo, preservando o original) — de
graça, sem gerar exemplos.
