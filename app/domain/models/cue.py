from enum import Enum
from typing import Dict, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class CueCode(str, Enum):
    """Taxonomia canonica de pistas de phishing (issue #5).

    Espelha, com os MESMOS 10 codigos, a taxonomia ja semeada no
    backend Go (phishing-quest-api, migration
    V20260917110000__add_cues_tables.sql, com UUIDs fixos). Tres
    mecanicas inteiras do Go dependem de saber quais pistas cada item
    contem (byCue em /me/stats, selecao adaptativa, fila Leitner) e
    nenhuma delas tem alimentacao automatica sem este campo.

    Enum (nao string livre) de proposito: e o que restringe o
    `with_structured_output` do LLM a nao inventar codigo fora da
    taxonomia -- o principal risco que esta issue existe para evitar.
    Mesmo `str(Enum)` gotcha de `Difficulty` (ver #2): sempre usar
    `.value` explicitamente, nunca o membro cru em f-string/`.format()`.
    """

    SENDER_DOMAIN_MISMATCH = "sender_domain_mismatch"
    TYPOSQUAT = "typosquat"
    HOMOGLYPH = "homoglyph"
    URGENCY = "urgency"
    AUTHORITY = "authority"
    GENERIC_GREETING = "generic_greeting"
    CREDENTIAL_REQUEST = "credential_request"
    LINK_TEXT_MISMATCH = "link_text_mismatch"
    UNEXPECTED_ATTACHMENT = "unexpected_attachment"
    SCARCITY = "scarcity"


# Definicoes operacionais das pistas -- as MESMAS de `cues.descricao_pt`,
# que o especialista ve ao anotar (issue #35; urgency e scarcity
# reescritas na migration V20261027120000). O gerador e o anotador as
# cegas usam este texto, para LLM e especialistas julgarem com o mesmo
# codebook; tests/integration/test_email_cues_persistence.py confere que
# continua identico ao banco.
DEFINICOES_OPERACIONAIS: Dict[CueCode, str] = {
    CueCode.SENDER_DOMAIN_MISMATCH: (
        "O dominio do remetente exibido nao corresponde ao dominio oficial da organizacao "
        "que a mensagem alega representar (ex.: nome da empresa no texto, mas dominio de "
        "e-mail generico ou de terceiros)."
    ),
    CueCode.TYPOSQUAT: (
        "Dominio com um ou mais caracteres trocados, adicionados ou removidos de proposito "
        "para parecer o dominio oficial (ex.: banc0-brasil.com em vez de bancodobrasil.com.br)."
    ),
    CueCode.HOMOGLYPH: (
        "Caractere visualmente identico ou muito parecido substituido no dominio ou no texto "
        'para enganar a leitura rapida (ex.: "rn" no lugar de "m", "l" minusculo no lugar de '
        '"I" maiusculo).'
    ),
    CueCode.URGENCY: (
        "Apelo a agir rapidamente, com prazo curto ou consequencia iminente, que pressiona a "
        "vitima a nao verificar antes de agir. Inclui prazo para cumprir uma obrigacao ou "
        'evitar uma sancao (ex.: "regularize ate sexta-feira").'
    ),
    CueCode.AUTHORITY: (
        "Apelo a autoridade de uma figura ou instituicao (banco, governo, chefia, TI interna) "
        "para induzir obediencia sem questionamento."
    ),
    CueCode.GENERIC_GREETING: (
        'Saudacao impessoal, sem usar o nome do destinatario (ex.: "Prezado cliente", "Caro '
        'usuario"), quando seria esperado tratamento nominal numa comunicacao legitima daquele '
        "tipo."
    ),
    CueCode.CREDENTIAL_REQUEST: (
        "Solicitacao direta de senha, codigo de verificacao, dado de cartao ou outro segredo "
        "de autenticacao."
    ),
    CueCode.LINK_TEXT_MISMATCH: (
        "O texto exibido do link sugere um destino diferente do endereco real para onde ele "
        "aponta."
    ),
    CueCode.UNEXPECTED_ATTACHMENT: (
        "Anexo presente sem justificativa clara no contexto da mensagem, ou de tipo incomum "
        "para o que esta sendo descrito."
    ),
    CueCode.SCARCITY: (
        "Apelo a escassez: oferta, vaga ou beneficio limitado em quantidade, ou disponivel so "
        'por tempo limitado (ex.: "restam 3 vagas", "so para os 50 primeiros", "promocao '
        'valida hoje"), usado para induzir acao impulsiva. Prazo para cumprir uma obrigacao e '
        "urgency, nao scarcity."
    ),
}

# Em que parte do item a evidencia da pista esta -- mesmo vocabulario
# do `campo` das anotacoes dos especialistas (expert_evaluation.Campo),
# para os spans do LLM e os dos especialistas serem comparaveis.
CampoDaPista = Literal["conteudo", "assunto", "remetente"]


class Cue(BaseModel):
    """Uma pista anotada num item -- saida do LLM (nao entrada, ao
    contrario de `nivel`/`is_malicious`/`channel`; ver o comentario de
    `GeneratedItemDraft` sobre essa distincao). Por isso o mesmo
    formato serve tanto no draft do gerador quanto no `PhishingEmail`
    persistido: nao ha remapeamento entre os dois, so passagem direta.

    `span_start`/`span_end` sao opcionais de proposito (issue #5, passo
    4): se o modelo nao localizar a evidencia com precisao no
    `conteudo`, e preferivel devolver ambos `None` a um intervalo
    errado -- um destaque no lugar errado e pior que nenhum destaque.
    `ResponseGenerator._validar_cues` e quem aplica essa regra depois
    da geracao (passo 5): confere `conteudo[span_start:span_end] ==
    evidencia` e zera os dois campos quando nao bate.
    """

    code: CueCode
    evidencia: str = Field(
        description="Trecho literal do conteudo que evidencia esta pista -- pedido "
        "explicitamente para reduzir alucinacao: o modelo precisa apontar onde esta, "
        "nao so alegar que a pista existe."
    )
    span_start: Optional[int] = None
    span_end: Optional[int] = None
    # Campo em que `span_start`/`span_end` se aplicam (lote-piloto 2,
    # 27/10/2026): antes os spans so eram calculados sobre o `conteudo`,
    # e pistas no remetente (sender_domain_mismatch) ficavam sem posicao.
    # None em pistas anteriores a esta mudanca (span relativo ao
    # conteudo) ou quando a evidencia nao foi localizada.
    campo: Optional[CampoDaPista] = None


class CueTaxonomyEntry(BaseModel):
    """Uma LINHA da taxonomia (tabela `cues`), issue #35 -- o vocabulario
    que o anotador humano ve. Nao e `Cue`: aquele representa uma
    ANOTACAO (code + evidencia + span) num item, este representa uma
    entrada do vocabulario. Reaproveita `CueCode` para o codigo.
    """

    id: UUID
    code: CueCode
    label_pt: str
    descricao_pt: str
    category: Literal["technical", "psychological"]
    ativo: bool
