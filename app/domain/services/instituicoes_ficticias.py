"""Lista versionada de identidades ficticias de organizacao (correcoes
de qualidade do piloto 5, item 2.1).

Fornece ao prompt de geracao a identidade PRONTA de uma organizacao
(nome-base, sigla, dominio oficial) em vez de pedir ao LLM para
"inventar um nome ficticio" -- a instrucao que causava 22 das 25 falhas
do piloto 4 (ver docstring de InstituicaoFicticia). `VariationSampler`
sorteia uma entrada por item, balanceada como as demais dimensoes da
ficha; a requisicao de `/generate/batch` pode fixar uma so para o lote
inteiro (`BatchGenerationRequest.instituicao`), para a planilha do
protocolo controlar a instituicao por celula.

Cada nome-base e CONFERIDO (ver
tests/unit/test_instituicoes_ficticias.py) contra
`item_validation.encontrar_instituicoes_reais`,
`encontrar_dominios_caricatos` e `encontrar_marcadores`: nenhuma
entrada aqui pode disparar esses detectores, senao o proprio item
recem-criado com esta identidade seria barrado e mandado gerar de novo
-- exatamente o laco que este arquivo existe para romper. Ampliar a
lista e so acrescentar entradas que passem na mesma conferencia.
"""

from app.domain.models.instituicao_ficticia import InstituicaoFicticia

# Nomes de marca neutros quanto ao setor (nenhum contem "banco",
# "universidade" etc.) -- ver docstring de InstituicaoFicticia sobre o
# porque disso ser proposital. Oito entradas bastam para um ciclo
# balanceado (_Ciclo) sem repetir a mesma instituicao duas vezes antes
# de esgotar a lista, no tamanho tipico de lote do protocolo (10-50
# itens).
INSTITUICOES: tuple[InstituicaoFicticia, ...] = (
    InstituicaoFicticia(nome_base="Vallonta", sigla="VAL", dominio_oficial="vallonta.com.br"),
    InstituicaoFicticia(nome_base="Nortega", sigla="NTG", dominio_oficial="nortega.com.br"),
    InstituicaoFicticia(
        nome_base="Confiar Nacional", sigla="CNL", dominio_oficial="confiarnacional.com.br"
    ),
    InstituicaoFicticia(
        nome_base="Horizonte Mais", sigla="HRM", dominio_oficial="horizontemais.com.br"
    ),
    InstituicaoFicticia(nome_base="ConectaBR", sigla="CBR", dominio_oficial="conectabr.com.br"),
    InstituicaoFicticia(nome_base="Estrela Mix", sigla="ESM", dominio_oficial="estrelamix.com.br"),
    InstituicaoFicticia(nome_base="Grão Sul", sigla="GRS", dominio_oficial="graosul.com.br"),
    InstituicaoFicticia(
        nome_base="Prisma Nacional", sigla="PRN", dominio_oficial="prismanacional.com.br"
    ),
)
