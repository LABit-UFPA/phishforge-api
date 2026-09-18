from pydantic import BaseModel, Field

from app.domain.models.difficulty import Difficulty


class QueryRequest(BaseModel):
    difficulty: Difficulty
    user_context: str = Field(alias="context")
    # Default True preserva o comportamento historico de quem ja chama
    # /generate sem esse campo (issue #3): continua gerando phishing.
    is_malicious: bool = True

    class Config:
        populate_by_name = True
        from_attributes = True

class QueryResponse(BaseModel):
    text: str
    score: float | None = None
    id: str | None = None
    payload: dict | None = None # type: ignore

class RepoRequest(BaseModel):
    url: str