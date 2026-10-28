from pydantic import BaseModel, ConfigDict


class InstituicaoFicticia(BaseModel):
    """Identidade ficticia completa de uma organizacao (nome-base, sigla
    e dominio oficial), fornecida pelo CODIGO ao prompt de geracao
    (correcoes de qualidade do piloto 5, item 2.1).

    `frozen=True`: alem de expressar que e um objeto de valor (nunca
    mutado depois de criado -- so comparado ou trocado por outro), e o
    que torna a instancia hashable no pydantic v2. Sem isso,
    `BaseModel` define `__eq__` (comparacao por campo) sem definir
    `__hash__`, e a regra do proprio Python desliga o hash por
    omissao -- `set(INSTITUICOES)` ou `{ficha.instituicao for ...}`
    levantam `TypeError: unhashable type`. O codigo de producao nunca
    muta uma instancia (so compara com `==`/`!=` ou troca por outra),
    entao isto nao muda comportamento nenhum alem de habilitar o hash.

    Antes desta mudanca, a regra de forma mandava o LLM "inventar um
    nome ficticio e plausivel" -- e repetia a palavra "ficticia/o" 3
    vezes no mesmo prompt. O `gpt-4o-mini` levava a instrucao ao pe da
    letra e escrevia literalmente "Universidade Ficticia"; o validador
    pos-geracao barra esse literal (ver `_NOME_GENERICO` em
    item_validation.py) e manda gerar de novo -- com a MESMA instrucao,
    entao o modelo reincidia. 22 das 25 falhas do piloto 4 vinham dai.
    A correcao e nao pedir mais para o modelo inventar nada: a
    identidade sai pronta da ficha (ver VariationSampler e
    instituicoes_ficticias.py).

    `nome_base` e deliberadamente SEM palavra de categoria (nunca
    "Universidade X" ou "Banco X" prontos): o VariationSampler e
    generico entre os 5 eixos de contexto do protocolo e nao sabe se o
    cenario pedido e universidade, banco, orgao publico, varejo ou
    telecom (ver docstring de VariationSampler) -- um nome-base pronto
    como "Banco Vallonta" ficaria errado num cenario de universidade.
    O LLM, que ja recebe o cenario no prompt, e quem compoe o nome de
    categoria com este nome-base ("Universidade Vallonta", "Banco
    Vallonta"); nome-base, sigla e dominio sao sempre usados juntos e
    exatamente como estao -- o LLM nunca inventa nenhum dos tres.
    """

    model_config = ConfigDict(frozen=True)

    nome_base: str
    sigla: str
    dominio_oficial: str
