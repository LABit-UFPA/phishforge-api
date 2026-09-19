from pydantic import BaseModel

from app.domain.models.channel_content import (
    PhoneCallContent,
    PixQrContent,
    SmsContent,
    WebsiteContent,
    WhatsAppContent,
)


class WebsiteItemDraft(BaseModel):
    """Contrato do structured output do LLM para `channel=website`
    (issue #6). Schema PROPRIO, separado de `GeneratedItemDraft`
    (email) -- email fica intocado por esta issue, e nao faz sentido
    pedir ao LLM os campos de email (receptor/assunto/...) quando o
    canal e outro.

    Sem `cues`/`premise_alignment` (issues #5/#9) de proposito: a
    adaptacao da taxonomia de pistas por canal e decisao de pesquisa
    explicitamente fora do escopo desta entrega (ver comentario da
    issue #6) -- fica para quando os 6 canais estiverem completos.
    """

    content: WebsiteContent
    explicacao: str
    categoria: str


class PhoneCallItemDraft(BaseModel):
    """Contrato do structured output do LLM para `channel=phone_call`."""

    content: PhoneCallContent
    explicacao: str
    categoria: str


class PixQrItemDraft(BaseModel):
    """Contrato do structured output do LLM para `channel=pix_qr`."""

    content: PixQrContent
    explicacao: str
    categoria: str


class SmsItemDraft(BaseModel):
    """Contrato do structured output do LLM para `channel=sms` (issue
    #6, desbloqueado pela `phishing-quest-api` #68)."""

    content: SmsContent
    explicacao: str
    categoria: str


class WhatsAppItemDraft(BaseModel):
    """Contrato do structured output do LLM para `channel=whatsapp`
    (issue #6, desbloqueado pela `phishing-quest-api` #68)."""

    content: WhatsAppContent
    explicacao: str
    categoria: str
