from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class PhishingEmailResponse(BaseModel):
    """Response DTO para geração de email de phishing individual.

    Ainda não usado como `response_model` pelos endpoints reais (que
    devolvem dict solto -- mesmo caso das outras DTOs mortas cobertas
    na issue #8). Mantido consistente com o shape real mesmo assim.
    """
    id: str
    receptor: str
    remetente: str
    assunto: str
    conteudo: str
    explicacao: str
    nivel: str
    categoria: str
    links: List[str]
    is_malicious: bool


class BatchGenerationResponse(BaseModel):
    """Response DTO para geração em lote de emails de phishing"""
    total_requested: int = Field(ge=0, description="Total de emails solicitados")
    total_generated: int = Field(ge=0, description="Total de emails gerados com sucesso")
    distribution: Dict[str, int] = Field(description="Distribuição por dificuldade")
    examples: List[PhishingEmailResponse] = Field(description="Lista de emails gerados")


class BatchGenerationError(BaseModel):
    """Response DTO para erros na geração em lote"""
    error: str = Field(description="Mensagem de erro")


class EmailListResponse(BaseModel):
    """Response DTO para listagem de emails"""
    emails: List[PhishingEmailResponse] = Field(description="Lista de emails")
    count: int = Field(ge=0, description="Quantidade de emails retornados")


class DebugStatisticsResponse(BaseModel):
    """Response DTO para debug de estatísticas"""
    raw_stats: Dict[str, Any] = Field(description="Estatísticas brutas")
    raw_stats_type: str = Field(description="Tipo das estatísticas brutas")
    by_difficulty_type: str = Field(description="Tipo da distribuição por dificuldade")
    by_category_type: str = Field(description="Tipo da distribuição por categoria")
    total_type: str = Field(description="Tipo do total")
    recent_count_type: str = Field(description="Tipo da contagem recente")


class DeleteEmailResponse(BaseModel):
    """Response DTO para deleção de email"""
    message: str = Field(description="Mensagem de confirmação")


class ErrorResponse(BaseModel):
    """Response DTO genérico para erros"""
    error: str = Field(description="Mensagem de erro")
    error_type: Optional[str] = Field(None, description="Tipo do erro")


class UserAnswerEvaluationResponse(BaseModel):
    """Response DTO para avaliação da justificativa do usuário"""
    score: int = Field(ge=0, le=5, description="Nota de 0 a 5 para a qualidade do raciocínio")
    feedback: str = Field(description="Feedback detalhado explicando a nota")
    strengths: List[str] = Field(description="Pontos fortes identificados")
    improvements: List[str] = Field(description="Pontos que podem ser melhorados")
    # Aditivo (issue #4): quem ja consome so score/feedback/strengths/
    # improvements continua funcionando sem mudanca nenhuma.
    acerto_por_sorte: bool = Field(
        default=False,
        description="True se o veredito bateu com o rótulo verdadeiro mas a justificativa não sustenta a conclusão",
    )