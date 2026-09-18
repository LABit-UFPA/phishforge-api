from typing import List

from pydantic import BaseModel, Field

from app.domain.models.difficulty import Difficulty


class BatchGenerationRequest(BaseModel):
    """Request DTO para geração em lote de emails de phishing.

    Ainda não usado por `POST /api/v1/generate/batch` (o endpoint
    recebe `Body(..., embed=True)` solto -- ver issue #8, item 4).
    O tipo de `difficulties` é corrigido aqui mesmo assim, e o
    endpoint tipa o parâmetro solto com `list[Difficulty]`
    diretamente, para as duas formas ficarem consistentes até o
    endpoint passar a usar este DTO de fato.
    """
    context: str = Field(description="Contexto para geração dos emails")
    difficulties: List[Difficulty] = Field(description="Lista de dificuldades desejadas")
    total: int = Field(default=10, ge=1, le=10, description="Total de emails a serem gerados")


class EmailSearchRequest(BaseModel):
    """Request DTO para busca de emails"""
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