from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel

class PhishingEmail(BaseModel):
    receptor: str
    remetente: str
    assunto: str
    conteudo: str
    explicacao: str
    nivel: str
    categoria: str
    links: List[str]
    # Default True preserva o comportamento historico (todo item ate a
    # issue #3 era phishing por construcao) para quem constroi este
    # modelo sem passar o campo explicitamente. O endpoint sempre passa
    # o valor explicito, vindo da request ja validada -- assim como
    # `nivel`, `is_malicious` e entrada da geracao, nunca faz parte do
    # que o LLM emite (ver GeneratedItemDraft e o comentario da #11).
    is_malicious: bool = True
    # Opcionais porque um PhishingEmail recem-construido pelo gerador
    # (antes do INSERT) nao tem nenhum dos tres -- so existem apos a
    # persistencia. PhishingEmailRepository._row_to_model ja passava os
    # tres como kwargs desde sempre; sem declara-los aqui, o Pydantic
    # v2 os descartava em silencio (extra='ignore' e o default), e
    # GET /api/v1/emails e GET /api/v1/emails/{id} devolviam o objeto
    # SEM id -- issue #24. Mesmo precedente de GenerationJob.
    id: Optional[UUID] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None