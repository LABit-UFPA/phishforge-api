from typing import List, Literal

from pydantic import BaseModel, Field

from app.domain.models.link_ref import LinkRef


class WebsiteContent(BaseModel):
    """Shape de `content_json` para `channel=website` (issue #6).

    Chaves em ingles, alinhadas com o que `item_draft_service.go`
    (backend Go) ja escreve para este canal -- `url`/`title` existem
    dos dois lados; `visible_content` e campo novo que o gerador
    precisa emitir e que o Go ainda nao tinha motivo de ter (o
    rascunho manual la nao gerava pagina inteira).
    """

    url: str = Field(description="URL do site falso, visualmente parecida com a legitima")
    title: str = Field(description="Titulo da pagina (tag <title> ou cabecalho principal)")
    visible_content: str = Field(
        description="Texto visivel da pagina -- o que a vitima veria renderizado"
    )


class PhoneCallContent(BaseModel):
    """Shape de `content_json` para `channel=phone_call` (vishing).

    Sem elemento visual: as pistas de phishing neste canal sao
    inteiramente verbais (pressa na fala, pedido de codigo por
    telefone, autoridade fingida) -- ver `evidencia` das pistas quando
    a taxonomia por canal (#5) for revisada.
    """

    caller: str = Field(description="Numero ou identificacao de chamada exibida (spoofed)")
    transcript: str = Field(description="Transcricao do roteiro falado pelo golpista")


class PixQrContent(BaseModel):
    """Shape de `content_json` para `channel=pix_qr`.

    `amount` e string, NUNCA numero: o Go modela valor monetario como
    string de proposito (`map[string]string`), e float para dinheiro e
    problema por si so (arredondamento) -- se um dia virar numero, tem
    que ser decimal, nunca float. A pista central deste canal costuma
    ser `recipient` divergente do esperado, nao dominio (nao ha
    dominio num QR Code).
    """

    payload: str = Field(description="Payload bruto do QR Code (BR Code)")
    recipient: str = Field(description="Nome do recebedor exibido no comprovante/confirmacao")
    amount: str = Field(description="Valor da cobranca, como string (ex.: '149.90')")
    pix_key: str = Field(description="Chave Pix exibida (CPF/CNPJ/e-mail/telefone/aleatoria)")


class SmsContent(BaseModel):
    """Shape de `content_json` para `channel=sms` (issue #6, desbloqueado
    pela `phishing-quest-api` #68: o shape exige `links` aninhado, que o
    `buildDraftContent` do Go so passou a aceitar depois daquela issue).

    Sem `assunto`: SMS nao tem campo de assunto -- diferente de email,
    o remetente e o proprio texto sao os unicos sinais disponiveis.
    `links` reaproveita `LinkRef` (issue #5): mesma pista
    `link_text_mismatch` faz sentido aqui (um link encurtado cujo texto
    exibido nao bate com o destino).
    """

    sender: str = Field(description="Numero ou identificacao do remetente exibido")
    text: str = Field(description="Texto da mensagem SMS -- curto, sem formatacao")
    links: List[LinkRef] = Field(
        default_factory=list,
        description="Links presentes na mensagem, se houver (comum em SMS ser encurtado)",
    )


class WhatsAppMessage(BaseModel):
    """Uma mensagem dentro do historico de conversa de `WhatsAppContent`.

    `author` distingue quem enviou -- `contact` e o golpista/organizacao
    simulada, `user` e uma resposta do proprio destinatario (util para
    simular um dialogo, nao so uma mensagem solta).
    """

    author: Literal["contact", "user"] = Field(
        description="Quem enviou a mensagem: 'contact' (golpista/organizacao) ou 'user' (destinatario)"
    )
    text: str = Field(description="Texto da mensagem")


class WhatsAppContent(BaseModel):
    """Shape de `content_json` para `channel=whatsapp` (issue #6,
    desbloqueado pela `phishing-quest-api` #68).

    `messages` e um HISTORICO (lista), nao uma mensagem unica: golpes
    de WhatsApp tipicamente se desenrolam em varias mensagens (contato
    inicial, resposta a duvida, pressao final). Sem `links` no nivel
    do content -- um link, quando existir, aparece dentro do `text` de
    uma mensagem especifica, como aconteceria de verdade no app.
    """

    sender: str = Field(description="Numero de telefone do remetente exibido")
    display_name: str = Field(description="Nome de exibicao do contato/organizacao simulada")
    messages: List[WhatsAppMessage] = Field(
        description="Historico de mensagens da conversa, em ordem cronologica"
    )
