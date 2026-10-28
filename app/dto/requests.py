from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.domain.models.channel import Channel
from app.domain.models.difficulty import Difficulty
from app.domain.models.instituicao_ficticia import InstituicaoFicticia


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
    # Por ora o endpoint so aceita 1.0 (lote so de phishing) e responde
    # 422 para os demais; o intervalo 0..1 fica aqui para quando a
    # mistura com itens legitimos for reabilitada.
    malicious_ratio: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Proporção de itens maliciosos. Por ora só 1.0 (todos phishing) é aceito; outros valores retornam 422.",
    )
    # Issue #6: um canal por lote (nao misto) -- mesmo escopo do
    # endpoint unico. Por ora so EMAIL e aceito; os demais dao 422 no
    # endpoint (ver app.domain.models.channel.GENERATION_SUPORTADOS).
    channel: Channel = Field(
        default=Channel.EMAIL,
        description="Canal do lote. Por ora só 'email' é aceito; os demais retornam 422.",
    )
    # Lote-piloto de 26/10/2026: a dedup so comparava itens do proprio
    # lote, entao os varios lotes de uma mesma celula do protocolo podiam
    # repetir itens entre si. Quem pede escolhe quais lotes entram na
    # comparacao -- explicito, para um lote-piloto nunca entrar por acaso.
    dedup_job_ids: List[UUID] = Field(
        default_factory=list,
        description=(
            "Lotes anteriores (job_id) cujos itens aceitos também entram na checagem de "
            "quase-duplicata. Use os outros lotes da mesma célula; não inclua lotes-piloto."
        ),
    )
    seed: Optional[int] = Field(
        default=None,
        ge=0,
        description=(
            "Semente do sorteio das fichas de variação. Omitida, o sistema sorteia uma e a "
            "registra em run_metadata, para o lote poder ser reproduzido."
        ),
    )
    # Correcoes de qualidade do piloto 5, item 2.1: override da
    # identidade ficticia da organizacao para o LOTE inteiro (nome-base,
    # sigla, dominio oficial), para a planilha do protocolo fixar a
    # instituicao por celula. Omitido, cada item sorteia uma instituicao
    # da lista versionada (balanceado -- ver VariationSampler e
    # instituicoes_ficticias.py).
    instituicao: Optional[InstituicaoFicticia] = Field(
        default=None,
        description=(
            "Override da identidade fictícia da organização (nome-base, sigla, domínio "
            "oficial) para o lote inteiro. Omitido, cada item sorteia uma instituição "
            "diferente da lista versionada."
        ),
    )


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