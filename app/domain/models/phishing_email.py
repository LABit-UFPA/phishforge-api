from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.domain.models.channel import Channel
from app.domain.models.cue import Cue
from app.domain.models.link_ref import LinkRef
from app.domain.models.phish_scale import PhishScale

class PhishingEmail(BaseModel):
    # Optional desde a issue #6 (multicanal): so `channel=email`
    # preenche estes quatro -- os outros canais (website/phone_call/
    # pix_qr) usam `content_json`. O validador abaixo garante que
    # exatamente um dos dois grupos vem preenchido, nunca os dois nem
    # nenhum -- mesma regra do CHECK `ck_conteudo_por_canal` no banco.
    receptor: Optional[str] = None
    remetente: Optional[str] = None
    assunto: Optional[str] = None
    conteudo: Optional[str] = None
    explicacao: str
    nivel: str
    categoria: str
    # List[LinkRef] desde a issue #5 (antes List[str]): texto exibido
    # separado do destino real, habilitando a pista link_text_mismatch.
    # Quebra-contrato deliberada -- ver docstring de LinkRef sobre o
    # porque agora e o momento certo (nenhum consumidor real ainda).
    links: List[LinkRef] = Field(default_factory=list)
    # Canal do item (issue #6). Default EMAIL preserva o
    # comportamento historico para quem constroi este modelo sem
    # passar o campo -- todo item ate esta issue era email por
    # construcao.
    channel: Channel = Channel.EMAIL
    # Conteudo dos canais NAO-email, shape variavel (ver
    # app/domain/models/channel_content.py -- WebsiteContent,
    # PhoneCallContent, PixQrContent). Guardado como dict solto aqui
    # (nao um Union tipado) porque o tipo especifico ja foi validado
    # uma vez no draft do LLM (ChannelItemDraft.content); recriar essa
    # validacao aqui duplicaria a fonte de verdade do shape.
    content_json: Optional[Dict[str, Any]] = None
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

    @model_validator(mode="after")
    def _conteudo_bate_com_o_canal(self) -> "PhishingEmail":
        """Espelha `ck_conteudo_por_canal` (migration V20260919130000)
        no nivel do modelo: falha na construcao do objeto Python, nao
        so no INSERT -- um erro de shape aparece antes, mais perto de
        onde foi cometido.
        """
        campos_email = (self.receptor, self.remetente, self.assunto, self.conteudo)
        if self.channel == Channel.EMAIL:
            if any(campo is None for campo in campos_email):
                raise ValueError(
                    "channel=email exige receptor/remetente/assunto/conteudo preenchidos."
                )
            if self.content_json is not None:
                raise ValueError("channel=email nao deve ter content_json preenchido.")
        else:
            if self.content_json is None:
                raise ValueError(f"channel={self.channel.value} exige content_json preenchido.")
            if any(campo is not None for campo in campos_email):
                raise ValueError(
                    f"channel={self.channel.value} nao deve ter receptor/remetente/"
                    "assunto/conteudo preenchidos -- use content_json."
                )
        return self