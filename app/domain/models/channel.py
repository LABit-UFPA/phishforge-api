from enum import Enum


class Channel(str, Enum):
    """Os 6 canais que o backend Go modela em `items.channel` (issue
    #6). O CHECK de `phishing_emails.channel` aceita os 6 -- alinhado
    com o Go -- e a geracao agora sabe produzir todos: `EMAIL` (colunas
    antigas, sem mudanca), os 3 canais planos (website/phone_call/
    pix_qr) e `SMS`/`WHATSAPP` (desbloqueados pela `phishing-quest-api`
    #68, que ensinou `buildDraftContent` a aceitar valor aninhado --
    `links`/`messages` como array de objetos -- em vez de
    `map[string]string`).
    """

    EMAIL = "email"
    SMS = "sms"
    WHATSAPP = "whatsapp"
    WEBSITE = "website"
    PHONE_CALL = "phone_call"
    PIX_QR = "pix_qr"


# Canais que a geracao de fato sabe produzir. EMAIL usa as colunas
# antigas (sem content_json); os demais usam content_json (ver
# app/domain/models/channel_content.py). Todos os 6 membros de Channel
# desde a issue #68 do lado Go -- antes SMS/WHATSAPP ficavam de fora
# por exigirem valor aninhado que o Go ainda nao aceitava.
GENERATION_SUPORTADOS = frozenset(Channel)
