"""Validacoes deterministicas que rodam DEPOIS do LLM (lote-piloto de
26/10/2026), complementando `ResponseGenerator._validar_cues`.

Tres problemas do piloto que nao se resolvem com mais instrucao no
prompt, porque o prompt ja as dava:

1. Spans: 9 de 10 pistas voltaram sem posicao. Pedir ao LLM a posicao
   em caracteres de um trecho e pedir algo que ele nao faz bem; aqui a
   posicao e CALCULADA a partir da `evidencia` literal. Com isso, span
   nulo passa a ter um so significado: a evidencia nao e um trecho
   literal do `conteudo` (antes nao dava para distinguir "o modelo nao
   informou" de "a validacao zerou").
2. `generic_greeting` marcado em saudacao nominal ("Prezado Joao
   Silva"), apesar de o prompt (secao 3.5) ja dizer que a pista nao vale
   com personalizacao. Com a ficha, o nome do destinatario e conhecido
   pelo codigo, entao o falso positivo e detectavel.
3. Marcador no texto ("[Nome do Estudante]"): o item nao serve para
   avaliacao e precisa ser gerado de novo.

Tudo aqui e puro (sem LLM, sem I/O), testavel isoladamente.
"""

import re
from typing import List, Optional, Tuple

from pydantic import BaseModel, Field

from app.domain.models.cue import Cue, CueCode

# Marcador de template: texto entre colchetes ou chaves que COMECA com
# um substantivo tipico de campo a preencher. Ancorado no inicio de
# proposito: "[Clique aqui]" ou "[Acessar o Portal do Aluno]" sao texto
# ancora de link, nao marcador, e nao podem ser rejeitados.
_INICIO_DE_MARCADOR = (
    r"(?:nome|name|n[uú]mero|numero|data|valor|link|url|telefone|endere[cç]o|"
    r"cargo|empresa|institui[cç][aã]o|insira|inserir|seu|sua|destinat[aá]rio|"
    r"remetente|assinatura)"
)
_MARCADOR = re.compile(
    r"\[\s*" + _INICIO_DE_MARCADOR + r"\b[^\[\]\n]{0,60}\]"
    r"|\{\s*" + _INICIO_DE_MARCADOR + r"\b[^{}\n]{0,60}\}",
    re.IGNORECASE,
)

_ASPAS = "\"'“”‘’«»"


class PistaRemovida(BaseModel):
    code: CueCode
    evidencia: str
    motivo: str


class RelatorioValidacao(BaseModel):
    """O que a validacao pos-geracao fez com um item. Persistido em
    `phishing_emails.validacao`: e o que permite medir, no artigo,
    quantas vezes a autorrotulagem do LLM errou, em vez de corrigir em
    silencio.
    """

    # Pistas mantidas, mas cuja evidencia nao e trecho literal do texto
    # (span fica nulo).
    evidencias_nao_literais: List[CueCode] = Field(default_factory=list)
    pistas_removidas: List[PistaRemovida] = Field(default_factory=list)
    # Quantas vezes o item foi gerado de novo por causa de marcador.
    regeneracoes_por_marcador: int = 0
    # Aderencia a ficha: pistas-alvo que o LLM nao anotou, e pistas
    # anotadas que nao estavam no alvo. Vazias quando nao ha ficha.
    pistas_alvo_ausentes: List[CueCode] = Field(default_factory=list)
    pistas_fora_do_alvo: List[CueCode] = Field(default_factory=list)


def encontrar_marcadores(*textos: Optional[str]) -> List[str]:
    """Marcadores de template ("[Nome do Estudante]", "{nome}") em
    qualquer dos textos. Lista vazia = nada a corrigir.
    """
    achados: List[str] = []
    for texto in textos:
        if texto:
            achados.extend(m.group(0) for m in _MARCADOR.finditer(texto))
    return achados


def localizar_evidencia(conteudo: str, evidencia: str) -> Optional[Tuple[int, int, str]]:
    """Posicao (inicio, fim) da evidencia no conteudo e o trecho exato
    que casou, ou None se ela nao for literal. Tenta a evidencia como
    veio e, se falhar, sem aspas e espacos nas pontas -- o modelo costuma
    citar o trecho entre aspas.
    """
    for candidata in (evidencia, evidencia.strip().strip(_ASPAS).strip()):
        if candidata:
            inicio = conteudo.find(candidata)
            if inicio >= 0:
                return inicio, inicio + len(candidata), candidata
    return None


def calcular_spans(
    conteudo: str, cues: List[Cue], relatorio: Optional[RelatorioValidacao] = None
) -> List[Cue]:
    """Recalcula span_start/span_end de cada pista a partir da
    evidencia, ignorando o que o LLM tenha informado. Mantem a pista
    mesmo sem evidencia literal (o codigo pode estar certo mesmo quando
    a citacao nao esta -- mesma decisao da issue #5, passo 5).
    """
    resultado = []
    for cue in cues:
        achado = localizar_evidencia(conteudo, cue.evidencia)
        if achado is None:
            if relatorio is not None:
                relatorio.evidencias_nao_literais.append(cue.code)
            resultado.append(cue.model_copy(update={"span_start": None, "span_end": None}))
        else:
            inicio, fim, trecho = achado
            resultado.append(
                cue.model_copy(update={"span_start": inicio, "span_end": fim, "evidencia": trecho})
            )
    return resultado


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
    cues: List[Cue], pistas_alvo: List[CueCode], relatorio: RelatorioValidacao
) -> None:
    """Compara as pistas anotadas (ja validadas) com as pistas-alvo."""
    if not pistas_alvo:
        return
    anotadas = {cue.code for cue in cues}
    relatorio.pistas_alvo_ausentes = [p for p in pistas_alvo if p not in anotadas]
    relatorio.pistas_fora_do_alvo = sorted(
        (c for c in anotadas if c not in pistas_alvo), key=lambda c: c.value
    )
