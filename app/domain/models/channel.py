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


# Canais que /generate e /generate/batch aceitam. EMAIL usa as colunas
# antigas (sem content_json); os demais usam content_json (ver
# app/domain/models/channel_content.py).
#
# Por ora a geracao fica restrita a EMAIL: os outros 5 canais nao tem
# cues/phish_scale e a avaliacao por especialistas so aceita e-mail. O
# codigo deles continua no lugar (ramos `!= EMAIL` em generator.py e no
# BatchGenerationWorker, ResponseGenerator.generate_channel_item), so
# fica inalcancavel pelos endpoints. `Channel` segue com os 6 valores,
# alinhado com o Go, para itens ja gravados em outros canais continuarem
# legiveis. Para reabilitar todos: GENERATION_SUPORTADOS = frozenset(Channel)
GENERATION_SUPORTADOS = frozenset({Channel.EMAIL})
