from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from app.domain.models.cue import CueCode
from app.domain.models.instituicao_ficticia import InstituicaoFicticia


class VariationSpec(BaseModel):
    """Ficha de variacao de UM item (lote-piloto de 26/10/2026).

    O piloto do protocolo v2 (10 itens, contexto E1-M-A, nivel medio)
    descartou 5 itens como quase-duplicados, e os 5 aceitos eram o
    mesmo e-mail com o nome trocado. Causa: no lote, contexto,
    documentos fundidos, prompt e temperatura sao identicos para todos
    os itens -- a unica fonte de variacao era a temperatura. O proprio
    prompt ja registrava (issue #20) que pedir "variedade" em abstrato
    nao funciona, porque cada chamada nao sabe o que as outras geraram.

    A ficha resolve isso do lado do codigo: para cada item, o sistema
    sorteia os detalhes que o LLM convergia sempre para o mesmo valor.
    Ela NUNCA troca o cenario pedido -- so fixa detalhes dentro dele.

    E ENTRADA da geracao, como `nivel` e `is_malicious` (ver comentario
    de GeneratedItemDraft): nunca faz parte do schema que o LLM
    preenche. Persistida junto do item (`phishing_emails.variation_spec`)
    para o lote ser auditavel e reproduzivel.
    """

    # Identidade ficticia da organizacao deste item (piloto 5, item 2.1):
    # nome-base, sigla e dominio oficial, sorteados pelo codigo (ver
    # VariationSampler e instituicoes_ficticias.py). Substitui a
    # instrucao antiga de "invente um nome ficticio", que era a causa de
    # 22 das 25 falhas do piloto 4 -- ver docstring de InstituicaoFicticia.
    instituicao: InstituicaoFicticia
    # None => a saudacao deve ser generica (e o caso de `generic_greeting`
    # como pista-alvo, no nivel facil).
    nome_destinatario: Optional[str] = None
    # Endereco de e-mail LITERAL de quem recebe, montado pelo codigo a
    # partir do nome (ou generico, sem nome) e do dominio da propria
    # organizacao ou de um dominio pessoal (piloto 5, item 2.3): no
    # piloto 4, 17 dos 27 e-mails faceis salvos usavam
    # "aluno@universidadeficticia.com" porque so o nome vinha da ficha,
    # nao o dominio -- o LLM preenchia o endereco com a palavra
    # "ficticia", que o proprio validador de marcador barra.
    endereco_destinatario: str
    assinatura: str
    # Nome de quem assina, quando `assinatura` e uma pessoa (piloto 2: sem
    # isso, o modelo assinava sempre "Maria Silva" ou "Joao da Silva").
    nome_remetente: Optional[str] = None
    # Como deve ser o DOMINIO do endereco do remetente, derivado das
    # pistas-alvo (piloto 2: pistas de dominio pedidas com o remetente
    # escrito como um nome, sem endereco).
    endereco_remetente: str
    # Dominio LITERAL da pista de dominio ativa (typosquat ou
    # sender_domain_mismatch), quando uma delas e alvo -- calculado
    # deterministicamente pelo codigo a partir do dominio oficial da
    # ficha (piloto 5, item 2.2), nunca inventado pelo LLM. None quando
    # nenhuma pista de dominio e alvo (remetente usa o dominio oficial,
    # ou fica livre no facil sem pista de dominio).
    dominio_da_pista: Optional[str] = None
    # Onde `dominio_da_pista` deve aparecer: no endereco do remetente,
    # no destino (href) do link obrigatorio, ou nos dois -- depende do
    # nivel e de qual pista de dominio e o alvo (ver
    # VariationSampler._endereco_e_dominio_da_pista). None quando
    # `dominio_da_pista` e None.
    dominio_da_pista_em: Optional[Literal["remetente", "link", "remetente_e_link"]] = None
    estilo_assunto: str
    angulo_pretexto: str
    # None para item legitimo: a acao do item legitimo ja e definida pelo
    # nivel no prompt legitimo (link oficial ou instrucao textual).
    acao: Optional[str] = None
    tom: str
    estrutura: str
    abertura: str
    # Pistas que o item DEVE conter. Vazia para item legitimo. Distinta
    # de `cues` (o que o LLM anotou depois de escrever): comparar as
    # duas e uma medida de aderencia ao alvo.
    pistas_alvo: List[CueCode] = Field(default_factory=list)
