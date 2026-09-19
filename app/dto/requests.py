from typing import List

from pydantic import BaseModel, Field

from app.domain.models.channel import Channel
from app.domain.models.difficulty import Difficulty


class BatchGenerationRequest(BaseModel):
    """Request DTO para geração em lote de itens.

    Issue #8: antes, o endpoint recebia `Body(..., embed=True)` solto e
    revalidava total > 100 na mão -- o DTO existia mas não era usado, e
    o projeto acabou com três limites diferentes para o mesmo campo
    (aqui `le=10`, no endpoint `>100`, na documentação "máx: 10").
    Canônico agora é 100 (o que o endpoint já aplicava de fato), com o
    `Field` fazendo a validação em vez de um `if` manual -- mesma
    filosofia da issue #2 para `difficulty`: erro de entrada vira 422
    do Pydantic, não uma checagem duplicada que pode divergir de novo.
    """
    context: str = Field(description="Contexto para geração dos itens")
    difficulties: List[Difficulty] = Field(
        min_length=1, description="Lista de dificuldades desejadas (não pode ser vazia)"
    )
    total: int = Field(default=10, ge=1, le=100, description="Total de itens a serem gerados")
    malicious_ratio: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Proporção de itens maliciosos (1.0 = todos phishing, 0.0 = todos legítimos)",
    )
    # Issue #6: um canal por lote (nao misto) -- mesmo escopo do
    # endpoint unico. Default EMAIL preserva o comportamento historico.
    channel: Channel = Channel.EMAIL


class EmailSearchRequest(BaseModel):
    """Request DTO para busca de emails.

    Issue #8: passa a ser usado por `GET /api/v1/emails` via
    `Depends()` -- FastAPI trata cada campo como um query param
    independente, mesmo contrato de URL que os parâmetros soltos que
    existiam antes.
    """
    categoria: str | None = Field(None, description="Filtrar por categoria")
    nivel: str | None = Field(None, description="Filtrar por nível de dificuldade")
    search: str | None = Field(None, description="Termo de busca")
    limit: int = Field(default=50, ge=1, le=100, description="Limite de resultados")
    offset: int = Field(default=0, ge=0, description="Offset para paginação")


class UserAnswerEvaluationRequest(BaseModel):
    """Request DTO para avaliação da justificativa do usuário.

    Issue #4: o campo `phishing_example` carregava a premissa de que o
    item é sempre phishing no próprio nome -- renomeado para
    `item_content`. `is_malicious` (rótulo verdadeiro) e `user_verdict`
    (o que o usuário respondeu) são novos: sem eles, o avaliador não
    tinha como saber se o usuário acertou, nem em qual dos quatro casos
    (malicioso/legítimo x acertou/errou) a avaliação cai.
    """
    item_content: str = Field(
        description="O item (malicioso ou legítimo) que foi apresentado ao usuário"
    )
    is_malicious: bool = Field(
        description="Rótulo verdadeiro do item: True se é phishing, False se é legítimo"
    )
    user_verdict: bool = Field(
        description="O que o usuário respondeu: True para 'é phishing', False para 'é legítimo'"
    )
    user_justification: str = Field(
        description="A justificativa do usuário para o veredito acima"
    )