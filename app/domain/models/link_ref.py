from pydantic import BaseModel, Field


class LinkRef(BaseModel):
    """Um link com texto exibido separado do destino real (issue #5).

    Antes, `links` era `List[str]` -- so o destino, sem o texto que a
    vitima ve. Isso tornava a pista `link_text_mismatch` (texto do
    link diferente do destino real) inexpressavel: nao havia como
    anotar "o texto diz uma coisa, o href aponta para outra" com um
    unico campo. Shape em ingles (`text`/`href`, nao `texto`/`destino`)
    para bater com o contrato acordado com o backend Go
    (`phishing-quest-api` #68, que tambem desbloqueou `sms`/`whatsapp`
    na issue #6 por precisar do mesmo valor aninhado).

    Mudanca quebra-contrato de proposito: nao ha consumidor real hoje
    (o Go ainda nao integra com esta API -- issue `phishing-quest-api`
    #62 -- e o app Flutter fala com o Go, nao com esta API
    diretamente), entao o momento de trocar o shape é agora, antes de
    existir um cliente para quebrar.
    """

    text: str = Field(description="Texto exibido do link -- o que a vitima le")
    href: str = Field(description="Destino real do link (URL)")
