from enum import Enum


class Channel(str, Enum):
    """Os 6 canais que o backend Go modela em `items.channel` (issue
    #6). O CHECK de `phishing_emails.channel` aceita os 6 -- alinhado
    com o Go -- mas a geracao hoje so sabe produzir 4: `EMAIL` (colunas
    antigas, sem mudanca) e os 3 novos desta issue.

    `SMS`/`WHATSAPP` existem aqui so para o vocabulario bater com o
    Go; `GENERATION_SUPORTADOS` abaixo e o que a API de fato aceita
    como entrada -- pedir um dos dois de proposito da 422 explicito
    (ver generator.py), em vez de aceitar e falhar de forma obscura
    depois. Bloqueio: `buildDraftContent` no Go monta
    `map[string]string`, que nao comporta o array de objetos que o
    shape de sms/whatsapp exige (`messages`/`links` aninhados) --
    mesma causa do bloqueio de `links` na #5.
    """

    EMAIL = "email"
    SMS = "sms"
    WHATSAPP = "whatsapp"
    WEBSITE = "website"
    PHONE_CALL = "phone_call"
    PIX_QR = "pix_qr"


# Canais que a geracao de fato sabe produzir hoje. EMAIL usa as colunas
# antigas (sem content_json); os outros tres usam content_json (ver
# app/domain/models/channel_content.py).
GENERATION_SUPORTADOS = frozenset(
    {Channel.EMAIL, Channel.WEBSITE, Channel.PHONE_CALL, Channel.PIX_QR}
)
