from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.domain.models.cue import Cue
from app.domain.models.phish_scale import PhishScale

class PhishingEmail(BaseModel):
    receptor: str
    remetente: str
    assunto: str
    conteudo: str
    explicacao: str
    nivel: str
    categoria: str
    links: List[str]
    # Pistas anotadas pelo LLM na geracao, com codigo da taxonomia
    # compartilhada com o Go (issue #5). Passa direto de
    # GeneratedItemDraft, sem remapeamento -- e SAIDA do gerador, nao
    # entrada. Persistida em `email_cues` (PhishingEmailRepository) e
    # so populada de volta por get_by_id/get_by_ids (ver docstring dos
    # dois no repositorio) -- as demais listagens nao fazem o join,
    # decisao de escopo registrada no PR.
    cues: List[Cue] = Field(default_factory=list)
    # Estimativa a priori de dificuldade (issue #9), derivada de
    # `cues` + `premise_alignment` -- None para item legitimo, onde
    # "dificuldade de detectar phishing" nao se aplica. NAO confundir
    # com `nivel` (o pedido na request) nem com uma futura
    # `difficulty_calibrated` (medida a partir de tentativas reais no
    # backend Go, phishing-quest-api #66) -- ver docstring de
    # PhishScale para os tres significados.
    phish_scale: Optional[PhishScale] = None
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