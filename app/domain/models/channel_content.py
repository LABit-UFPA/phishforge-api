from pydantic import BaseModel, Field


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
