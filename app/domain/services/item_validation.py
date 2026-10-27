"""Validacoes deterministicas que rodam DEPOIS do LLM, complementando
`ResponseGenerator._validar_cues`. Tudo aqui e puro (sem LLM, sem I/O),
testavel isoladamente.

Lote-piloto 1 (26/10/2026):

1. Spans: 9 de 10 pistas voltaram sem posicao. A posicao passou a ser
   CALCULADA a partir da `evidencia` literal.
2. `generic_greeting` marcado em saudacao nominal ("Prezado Joao
   Silva"). Com a ficha, o nome do destinatario e conhecido pelo codigo.
3. Marcador no texto ("[Nome do Estudante]"): o item e gerado de novo.

Lote-piloto 2 (27/10/2026):

4. Marcadores que o filtro nao pegava ("[Informacoes de Contato]",
   "Universidade Exemplo"): o filtro so reconhecia colchetes que
   comecavam com certas palavras. Agora qualquer colchete ou chave e
   marcador, salvo texto de link, e nomes genericos ("Exemplo",
   "Fulano") tambem contam.
5. Remetente sem endereco de e-mail (4 de 9 itens): impossibilita
   pistas de dominio. O item e gerado de novo.
6. Spans so sobre o corpo: pistas no remetente ficavam sem posicao. A
   busca agora percorre remetente, assunto e corpo e registra o campo.
7. Pistas de dominio cuja evidencia nao tem dominio (um nome de setor
   anotado como sender_domain_mismatch): removidas.
8. Assunto repetido como primeira linha do corpo: removido do corpo.
"""

import re
import unicodedata
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from pydantic import BaseModel, Field

from app.domain.models.cue import CampoDaPista, Cue, CueCode

# Qualquer trecho entre colchetes ou chaves. Num e-mail real isso quase
# nunca aparece; no texto gerado, e quase sempre um campo de template que
# o modelo nao preencheu. A excecao (texto de link) e tratada em
# encontrar_marcadores.
_COLCHETES = re.compile(r"\[([^\[\]\n]{1,80})\](\(\s*https?://)?")
_CHAVES = re.compile(r"\{([^{}\n]{1,80})\}")

# Nomes de exemplo. Case-sensitive de proposito: "por exemplo" e texto
# normal; "Universidade Exemplo" e marcador.
_NOME_GENERICO = re.compile(r"\b(?:Exemplo|Example|XYZ|Fulano|Ciclano|Beltrano|Lorem ipsum)\b")
# Dominio de exemplo ("exemplo.com", "universidade-exemplo.edu.br").
_DOMINIO_DE_EXEMPLO = re.compile(
    r"\b[\w-]*(?:exemplo|example)[\w-]*(?:\.[\w-]+)*\.[a-z]{2,6}\b", re.IGNORECASE
)

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# Um dominio: rotulos separados por ponto, terminando num TLD de letras.
_DOMINIO = re.compile(r"\b[\w-]+(?:\.[\w-]+)*\.[a-z]{2,}\b", re.IGNORECASE)

# Pistas que, por definicao, estao num dominio (do remetente ou de link).
PISTAS_DE_DOMINIO = (CueCode.SENDER_DOMAIN_MISMATCH, CueCode.TYPOSQUAT)

# Ordem de busca da evidencia quando o campo declarado nao a contem.
_ORDEM_DOS_CAMPOS: Tuple[CampoDaPista, ...] = ("conteudo", "assunto", "remetente")

_ASPAS = "\"'“”‘’«»"


class PistaRemovida(BaseModel):
    code: CueCode
    evidencia: str
    motivo: str


class RelatorioValidacao(BaseModel):
    """O que a validacao pos-geracao fez com um item. Persistido em
    `phishing_emails.validacao`: e o que permite medir, no artigo,
    quantas vezes o LLM errou, em vez de corrigir em silencio.
    """

    # Pistas mantidas, mas cuja evidencia nao e trecho literal do item
    # (span fica nulo).
    evidencias_nao_literais: List[CueCode] = Field(default_factory=list)
    pistas_removidas: List[PistaRemovida] = Field(default_factory=list)
    # Quantas vezes o item foi gerado de novo, por motivo.
    regeneracoes_por_marcador: int = 0
    regeneracoes_por_remetente: int = 0
    # O assunto aparecia de novo como primeira linha do corpo e foi tirado.
    assunto_removido_do_corpo: bool = False
    # True quando `cues` e `premise_alignment` vieram do anotador as
    # cegas, e nao do proprio gerador.
    anotacao_cega: bool = False
    # O que o gerador declarou sobre o proprio texto (so com anotacao as
    # cegas, para comparar com o que o anotador encontrou).
    cues_autodeclaradas: List[CueCode] = Field(default_factory=list)
    premise_alignment_autodeclarado: Optional[str] = None
    # Aderencia a ficha: pistas-alvo que nao foram encontradas, e pistas
    # encontradas que nao estavam no alvo. Vazias quando nao ha ficha.
    pistas_alvo_ausentes: List[CueCode] = Field(default_factory=list)
    pistas_fora_do_alvo: List[CueCode] = Field(default_factory=list)


def _normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto)
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sem_acento).strip().casefold()


def encontrar_marcadores(
    *textos: Optional[str],
    textos_de_link: Iterable[str] = (),
    nomes_genericos: bool = True,
) -> List[str]:
    """Marcadores de template em qualquer dos textos: trecho entre
    colchetes ou chaves ("[Informacoes de Contato]", "{nome}") e, com
    `nomes_genericos`, nomes de exemplo ("Universidade Exemplo",
    "exemplo.com.br"). Colchete cujo texto e o de um link da lista
    `links`, ou seguido de "(http...)" (sintaxe de link), nao conta.
    Lista vazia = nada a corrigir.
    """
    links = {_normalizar(t) for t in textos_de_link if t}
    achados: List[str] = []
    for texto in textos:
        if not texto:
            continue
        for m in _COLCHETES.finditer(texto):
            if m.group(2) or _normalizar(m.group(1)) in links:
                continue
            achados.append(m.group(0))
        achados.extend(m.group(0) for m in _CHAVES.finditer(texto))
        if nomes_genericos:
            achados.extend(m.group(0) for m in _NOME_GENERICO.finditer(texto))
            achados.extend(m.group(0) for m in _DOMINIO_DE_EXEMPLO.finditer(texto))
    return achados


def endereco_de_email(texto: Optional[str]) -> Optional[str]:
    """O endereco de e-mail contido no texto ("Nome <a@b.com>" ou
    "a@b.com"), ou None se nao houver.
    """
    if not texto:
        return None
    m = _EMAIL.search(texto)
    return m.group(0) if m else None


def remover_assunto_repetido(assunto: str, conteudo: str) -> Tuple[str, bool]:
    """Tira a primeira linha do corpo quando ela repete o assunto (com ou
    sem o prefixo "Assunto:"). Devolve o corpo e se algo foi removido.
    """
    linhas = conteudo.split("\n")
    indice = next((i for i, linha in enumerate(linhas) if linha.strip()), None)
    if indice is None or not assunto.strip():
        return conteudo, False
    primeira = re.sub(r"^\s*assunto\s*:\s*", "", linhas[indice], flags=re.IGNORECASE)
    if _normalizar(primeira).rstrip(".:!") != _normalizar(assunto).rstrip(".:!"):
        return conteudo, False
    resto = linhas[indice + 1 :]
    while resto and not resto[0].strip():
        resto = resto[1:]
    return "\n".join(linhas[:indice] + resto), True


def localizar_evidencia(texto: str, evidencia: str) -> Optional[Tuple[int, int, str]]:
    """Posicao (inicio, fim) da evidencia no texto e o trecho exato que
    casou, ou None se ela nao for literal. Tenta a evidencia como veio e,
    se falhar, sem aspas e espacos nas pontas -- o modelo costuma citar o
    trecho entre aspas.
    """
    for candidata in (evidencia, evidencia.strip().strip(_ASPAS).strip()):
        if candidata:
            inicio = texto.find(candidata)
            if inicio >= 0:
                return inicio, inicio + len(candidata), candidata
    return None


def calcular_spans(
    campos: Dict[str, Optional[str]],
    cues: List[Cue],
    relatorio: Optional[RelatorioValidacao] = None,
) -> List[Cue]:
    """Recalcula span_start/span_end/campo de cada pista a partir da
    evidencia, ignorando posicoes informadas pelo LLM. Procura primeiro no
    campo declarado e depois em conteudo, assunto e remetente. Mantem a
    pista mesmo sem evidencia literal (o codigo pode estar certo mesmo
    quando a citacao nao esta -- issue #5, passo 5).
    """
    resultado = []
    for cue in cues:
        ordem = ([cue.campo] if cue.campo else []) + [
            c for c in _ORDEM_DOS_CAMPOS if c != cue.campo
        ]
        achado = None
        for campo in ordem:
            texto = campos.get(campo)
            if texto:
                achado = localizar_evidencia(texto, cue.evidencia)
                if achado is not None:
                    break
        if achado is None:
            if relatorio is not None:
                relatorio.evidencias_nao_literais.append(cue.code)
            resultado.append(cue.model_copy(update={"span_start": None, "span_end": None}))
        else:
            inicio, fim, trecho = achado
            resultado.append(
                cue.model_copy(
                    update={"span_start": inicio, "span_end": fim, "evidencia": trecho, "campo": campo}
                )
            )
    return resultado


def remover_pistas_de_dominio_sem_dominio(
    cues: List[Cue], relatorio: Optional[RelatorioValidacao] = None
) -> List[Cue]:
    """sender_domain_mismatch e typosquat sao, por definicao, sobre um
    dominio. Evidencia sem dominio ("Escritorio de Administracao
    Academica", "Universidade Exemplo") nao sustenta a pista.
    """
    mantidas = []
    for cue in cues:
        if cue.code in PISTAS_DE_DOMINIO and not _DOMINIO.search(cue.evidencia or ""):
            if relatorio is not None:
                relatorio.pistas_removidas.append(
                    PistaRemovida(
                        code=cue.code, evidencia=cue.evidencia, motivo="pista_de_dominio_sem_dominio"
                    )
                )
            continue
        mantidas.append(cue)
    return mantidas


def _primeira_linha(conteudo: str) -> str:
    linhas = conteudo.strip().splitlines()
    return linhas[0][:200] if linhas else ""


def saudacao_tem_nome(conteudo: str, evidencia: str, nome_destinatario: str) -> bool:
    """True se a saudacao (primeira linha do corpo) ou a propria
    evidencia citada trazem o primeiro nome do destinatario.
    """
    primeiro_nome = nome_destinatario.split()[0]
    padrao = re.compile(r"\b" + re.escape(primeiro_nome) + r"\b", re.IGNORECASE)
    return bool(padrao.search(_primeira_linha(conteudo)) or padrao.search(evidencia or ""))


def remover_saudacao_generica_falsa(
    conteudo: str,
    cues: List[Cue],
    nome_destinatario: Optional[str],
    relatorio: Optional[RelatorioValidacao] = None,
) -> List[Cue]:
    """Remove `generic_greeting` quando a saudacao usa o nome do
    destinatario sorteado na ficha. Sem nome conhecido, nao mexe.
    """
    if not nome_destinatario:
        return cues
    mantidas = []
    for cue in cues:
        if cue.code == CueCode.GENERIC_GREETING and saudacao_tem_nome(
            conteudo, cue.evidencia, nome_destinatario
        ):
            if relatorio is not None:
                relatorio.pistas_removidas.append(
                    PistaRemovida(
                        code=cue.code,
                        evidencia=cue.evidencia,
                        motivo="saudacao_com_nome_do_destinatario",
                    )
                )
            continue
        mantidas.append(cue)
    return mantidas


def registrar_aderencia(
    cues: List[Cue], pistas_alvo: Sequence[CueCode], relatorio: RelatorioValidacao
) -> None:
    """Compara as pistas encontradas (ja validadas) com as pistas-alvo."""
    if not pistas_alvo:
        return
    anotadas = {cue.code for cue in cues}
    relatorio.pistas_alvo_ausentes = [p for p in pistas_alvo if p not in anotadas]
    relatorio.pistas_fora_do_alvo = sorted(
        (c for c in anotadas if c not in pistas_alvo), key=lambda c: c.value
    )
