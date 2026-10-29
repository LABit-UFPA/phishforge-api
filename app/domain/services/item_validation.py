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

Teste local da versao do piloto 3 (27/10/2026):

9. Instituicao real (dominios da UFRJ num cenario sem nome de
   organizacao): o prompt pedia organizacao ficticia, mas nada conferia.
   O item e gerado de novo (ver instituicoes_reais.py).
10. "Acao Necessaria" no meio do assunto (2 de 3 itens): o prompt so
    proibia comecar com a formula. Em qualquer posicao, o item e gerado
    de novo.

Lote-piloto 3 (27/10/2026, 50 itens faceis, rodado antes dos itens 9-10):

11. "Prezados Alunos," no campo do destinatario (49 de 50): o item e
    gerado de novo se o destinatario nao for um endereco de e-mail. A
    saudacao vai no corpo, onde a pista generic_greeting ganha posicao.
12. Dominios caricatos ("fake", "donotclickhere", "universidade123"),
    puxados pelo proprio exemplo do prompt: o item e gerado de novo.
13. Links em Markdown no corpo (28 itens): "[texto](url)" vira so o
    texto e o destino vai para `links`, que e como o especialista ve o
    link (issue #51).
14. Contexto fundido do RAG com um e-mail pronto assinado pela UFRJ e
    marcadores "[Seu Nome]" (lote local de 27/10): a etapa de fusao
    escrevia o e-mail em vez de extrair conhecimento, e o mesmo modelo ia
    para todos os itens do lote. Alem do prompt, as linhas com
    instituicao real e os marcadores sao tirados do contexto fundido.

Correcoes de qualidade do piloto 5 (bloqueio de instituicao real so em
personificacao; "123456" como marcador):

15. O bloqueio de instituicao real disparava em qualquer MENCAO no
    corpo do e-mail ("entregue pelos Correios" num cenario de
    logistica), nao so em personificacao de fato (remetente, dominio,
    links). `encontrar_instituicoes_reais` continua igual para quem nao
    distingue campo (`limpar_contexto_fundido`); a checagem pos-geracao
    em `ResponseGenerator._problema_estrutural` passa a usar
    `encontrar_nomes_de_instituicoes_reais` (so remetente/destinatario/
    links) e `encontrar_dominios_reais` (qualquer campo -- um dominio
    real escrito em qualquer lugar e sempre personificacao).
16. "123456" como marcador: "Protocolo #123456" ainda se repetia mesmo
    depois do item 10 (proibir "Acao Necessaria"), porque o filtro de
    marcador nao cobria sequencia numerica de exemplo.
"""

import ipaddress
import re
import unicodedata
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlsplit

from pydantic import BaseModel, Field

from app.domain.models.cue import CampoDaPista, Cue, CueCode
from app.domain.models.link_ref import LinkRef
from app.domain.services.instituicoes_reais import (
    DOMINIOS_REAIS,
    ESTADOS,
    NOMES_DE_INSTITUICOES,
    SIGLAS_DE_ENSINO,
    SIGLAS_SO_EM_MAIUSCULAS,
)

# Qualquer trecho entre colchetes ou chaves. Num e-mail real isso quase
# nunca aparece; no texto gerado, e quase sempre um campo de template que
# o modelo nao preencheu. A excecao (texto de link) e tratada em
# encontrar_marcadores.
_COLCHETES = re.compile(r"\[([^\[\]\n]{1,80})\](\(\s*https?://)?")
_CHAVES = re.compile(r"\{([^{}\n]{1,80})\}")

# Nomes de exemplo. Case-sensitive de proposito: "por exemplo" e texto
# normal; "Universidade Exemplo" e marcador.
# "Ficticia" entrou no lote local de 27/10 ("Universidade Ficticia"): o
# modelo levou ao pe da letra a instrucao de inventar um nome ficticio.
_NOME_GENERICO = re.compile(
    r"\b(?:Exemplo|Example|XYZ|Fulano|Ciclano|Beltrano|Lorem ipsum|Fict[ií]ci[oa])\b"
)
# Endereco com nome de exemplo antes do arroba ("universidadeficticia@...").
_ENDERECO_DE_EXEMPLO = re.compile(
    r"\b[\w.+-]*(?:exemplo|example|ficticio|ficticia)[\w.+-]*@", re.IGNORECASE
)
# Dominio de exemplo ("exemplo.com", "universidade-exemplo.edu.br").
_DOMINIO_DE_EXEMPLO = re.compile(
    r"\b[\w-]*(?:exemplo|example|ficticio|ficticia)[\w-]*(?:\.[\w-]+)*\.[a-z]{2,6}\b", re.IGNORECASE
)
# Sequencia de digitos ascendentes classica de placeholder (piloto 5,
# item 2.6): "Protocolo #123456" se repetiu mesmo depois do item 10
# (proibir "Acao Necessaria"), porque aquela proibicao e so sobre o
# assunto e so sobre a formula, nunca sobre o numero de exemplo em si.
# Fronteira so por digito: "1234567" ou "0123456" nao contam (nao e o
# literal exato), mas "ORD123456" conta -- a sequencia em si ja
# denuncia que ninguem preencheu um numero de verdade.
_NUMERO_MARCADOR = re.compile(r"(?<!\d)123456(?!\d)")

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# Um dominio: rotulos separados por ponto, terminando num TLD de letras.
_DOMINIO = re.compile(r"\b[\w-]+(?:\.[\w-]+)*\.[a-z]{2,}\b", re.IGNORECASE)

# Pistas que, por definicao, estao num dominio (do remetente ou de link).
PISTAS_DE_DOMINIO = (CueCode.SENDER_DOMAIN_MISMATCH, CueCode.TYPOSQUAT)

# Ordem de busca da evidencia quando o campo declarado nao a contem.
_ORDEM_DOS_CAMPOS: Tuple[CampoDaPista, ...] = ("conteudo", "assunto", "remetente")

_ASPAS = "\"'“”‘’«»"


def _alternativas(termos: Iterable[str]) -> str:
    # Mais longos primeiro: "mato grosso do sul" antes de "mato grosso".
    return "|".join(re.escape(t) for t in sorted(termos, key=len, reverse=True))


# Instituicoes reais, sobre o texto normalizado (sem acento, minusculas).
# Fronteira de termo: qualquer caractere que nao seja letra ou digito
# (espaco, ponto, arroba, hifen, sublinhado), para "ufrj" casar com
# "@ufrj.edu.br" e "ufrj-portal.com".
_INSTITUICAO_POR_TERMO = re.compile(
    r"(?<![0-9a-z])(?:"
    + _alternativas(SIGLAS_DE_ENSINO + NOMES_DE_INSTITUICOES)
    + r")(?![0-9a-z])"
)
_INSTITUICAO_POR_ESTADO = re.compile(
    r"(?<![0-9a-z])(?:universidade|instituto)(?: federal| estadual)? (?:de|do|da|dos) (?:"
    + _alternativas(ESTADOS)
    + r")(?![0-9a-z])"
)
# Dominio real, com ou sem subdominio ("receita.gov.br"), mas nao como
# parte de outro dominio ("suportevivo.com.br" e ficticio).
_DOMINIO_REAL = re.compile(
    r"(?<![0-9a-z.-])(?:[0-9a-z-]+\.)*(?:"
    + _alternativas(DOMINIOS_REAIS)
    + r")(?![0-9a-z-]|\.[0-9a-z])"
)
# Siglas que so contam em maiusculas (sobre o texto sem acento, com caixa).
_SIGLA_MAIUSCULA = re.compile(
    r"(?<![0-9A-Za-z])(?:" + _alternativas(SIGLAS_SO_EM_MAIUSCULAS) + r")(?![0-9A-Za-z])"
)

# Dominio que se denuncia sozinho (piloto 3: "fake", "donotclickhere",
# "universidade123"). Ficam de fora, de proposito, termos de golpe
# realista: "seguranca-antifraude.com" e "antivirus-atualizacao.net" sao o
# tipo de dominio que o corpus deve ter.
_DOMINIO_CARICATO = re.compile(
    r"fake|fals[oa]|phish|golpe|do-?not-?click|dont-?click|nao-?cli(?:que|car)|malicio|hacker|123"
)

# Meta-narracao de "simulacao/conscientizacao" DENTRO do e-mail (achado da
# comparacao de modelos: o GPT-6 Luna assava "esta e uma simulacao de
# conscientizacao, nao e uma comunicacao real" no proprio corpo do phishing,
# em 56% dos itens -- o e-mail se auto-denuncia e vira inutil como exemplo).
# Alta precisao de proposito: so expressoes que um phishing real nunca traz.
# "treinamento"/"exercicio" sozinhos NAO entram (podem ser pretexto legitimo:
# "conclua seu treinamento obrigatorio"); so quando colados ao enquadramento
# educativo/de simulacao. A palavra "phishing" sozinha tambem NAO entra: um
# e-mail (ate um phishing como isca) pode cita-la, e nos 59 itens reais nenhum
# contaminado dependia SO dela (vinha sempre com simulac/conscientizac). Casa
# sobre texto ja normalizado (sem acento, minusculo) -- ver
# encontrar_disclaimer_de_simulacao. So aplicada a item MALICIOSO (ver
# _problema_estrutural): e-mail legitimo pode falar de simulacao/phishing (um
# aviso de conscientizacao verdadeiro), entao la nao conta como auto-denuncia.
_DISCLAIMER_SIMULACAO = re.compile(
    r"simulac|simulad[oa]|conscientizac|ficticio|ficticia"
    r"|material educativo|exercicio (?:educativo|de conscientiz|de seguranc)"
    r"|exemplo de conscientiz|para fins (?:deste exemplo|educativos|de treinamento)"
    r"|faz parte (?:do exercicio|da simulac|de uma simulac|deste exercicio)"
    r"|nao e (?:uma? )?(?:comunicac|aviso|e-?mail|mensagem|solicitac|oferta|cobranc)[a-z]* real"
    r"|nao e real"
)

# Sintaxe Markdown no corpo (issue #51; piloto 3: 28 de 50 itens).
_LINK_MARKDOWN = re.compile(r"\[([^\[\]\n]{1,200})\]\(\s*(https?://[^\s)]+)\s*\)")
_NEGRITO_MARKDOWN = re.compile(r"\*\*([^*\n]{1,200})\*\*")

# Assinatura/remetente de "notificacao automatica de sistema" (cenario C) que o
# modelo escreve como rotulo entre colchetes: "[SISTEMA ANR]", "[SISTEMA CBR]",
# "[AVISO AUTOMATICO]", "[NOTIFICACAO AUTOMATICA - CBR]", "[UCRV]", "[RMP]",
# "[ESM]" (4 das 5 falhas do Sonnet na comparacao, e o smoke de producao
# reproduziu outras). E so o rotulo de sistema -- nao um campo de template por
# preencher -- entao o colchete nao deve reprovar o item.
#
# Discriminador (DUAS condicoes, para nao desembrulhar placeholder por engano):
# 1. o miolo e CAIXA ALTA -- letras (com acento), digitos, espaco e separadores
#    comuns (. & / - en/em-dash), SEM minuscula; e
# 2. o miolo e, de fato, rotulo de SISTEMA (ver _e_rotulo_de_sistema): contem
#    uma palavra de sistema (SISTEMA, AVISO, AUTOMATICO, NOTIFICACAO...) OU a
#    sigla da instituicao da ficha ("[UCRV]", "[RMP]", "[ESM]").
# So a condicao 1 NAO bastava: "[LINK]", "[SEU NOME]", "[DATA]", "[CLIQUE AQUI]"
# tambem sao caixa alta e SAO placeholders -- desembrulha-los deixaria um campo
# de template passar pelo detector de marcador. Com a condicao 2 eles nao casam
# e seguem barrados por encontrar_marcadores. O rotulo e desembrulhado em tres
# lugares (ver desembrulhar_assinatura_de_sistema): linha isolada do corpo
# (sign-off), inicio do remetente (nome de exibicao do sistema) e inicio do
# assunto (tag). Nunca no meio de uma frase -- "[PORTAL]" no meio de um texto
# segue como marcador.
_ROTULO_DE_SISTEMA = r"\[([A-ZÀ-Þ0-9][A-ZÀ-Þ0-9 .&/–—-]{0,38})\]"
_ASSINATURA_LINHA = re.compile(r"^([ \t]*(?:[-–—·*]\s*)?)" + _ROTULO_DE_SISTEMA + r"([ \t.;:!-]*)$")
_ASSINATURA_PREFIXO = re.compile(r"^([ \t]*)" + _ROTULO_DE_SISTEMA)

# Palavras que so aparecem num rotulo de SISTEMA, nunca num placeholder de
# preenchimento (sobre texto sem acento, em maiusculas). Prefixos: "AUTOMATIC"
# cobre AUTOMATICO/AUTOMATICA; "NOTIFICAC" cobre NOTIFICACAO.
_SISTEMA_PALAVRAS = (
    "SISTEMA", "AVISO", "AUTOMATIC", "NOTIFICAC", "ALERTA", "COMUNICADO",
    "NO-REPLY", "NOREPLY", "NAO RESPONDER", "NAO-RESPONDER", "MAILER", "DAEMON",
)


def _e_rotulo_de_sistema(miolo: str, sigla: Optional[str]) -> bool:
    """True quando um miolo em CAIXA ALTA entre colchetes e rotulo de SISTEMA
    (a desembrulhar), nao um placeholder de preenchimento. Criterio: contem uma
    palavra de sistema OU a sigla da instituicao da ficha (como token, para
    "CBR" casar em "SISTEMA CBR"/"[CBR]" sem casar dentro de outra palavra).
    Sem sigla (sem ficha), so as palavras de sistema contam -- um acronimo solto
    e ambiguo demais e fica barrado."""
    normal = _sem_acento(miolo).upper()
    if any(p in normal for p in _SISTEMA_PALAVRAS):
        return True
    if sigla:
        sig = re.escape(_sem_acento(sigla).upper())
        return re.search(rf"(?<![A-Z0-9]){sig}(?![A-Z0-9])", normal) is not None
    return False

# TLDs e dominios de topo reservados para exemplo/teste (RFC 2606/6761): nunca
# existem num e-mail real. "localhost"/"local" idem. Comparados por rotulo do
# host (nao por regex de substring) para nao pegar "example-corp.com".
_TLDS_RESERVADOS = frozenset({"example", "test", "invalid", "localhost", "local"})
# "example" como 2o nivel ("example.com/.org/.net/.edu" -- o dominio de
# exemplo classico; "cbr-documentos.example" ja cai pelo TLD reservado).
_EXEMPLO_SEGUNDO_NIVEL = frozenset({"example"})
_TLDS_DE_EXEMPLO = frozenset({"com", "org", "net", "edu"})

# "Acao Necessaria", "Acao Requerida", "Acao Imediata Necessaria" (no
# singular ou plural), em qualquer posicao do assunto normalizado.
_FORMULA_DE_ASSUNTO = re.compile(
    r"(?<![0-9a-z])ac(?:ao|oes) (?:imediatas? )?(?:necessarias?|requeridas?|obrigatorias?)(?![0-9a-z])"
)


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
    regeneracoes_por_destinatario: int = 0
    regeneracoes_por_instituicao_real: int = 0
    regeneracoes_por_dominio_caricato: int = 0
    regeneracoes_por_assunto: int = 0
    regeneracoes_por_disclaimer: int = 0
    regeneracoes_por_link: int = 0
    # Assinaturas de "notificacao de sistema" (cenario C) desembrulhadas de
    # colchetes antes da checagem de marcador ("[SISTEMA ANR]" -> "SISTEMA
    # ANR") -- ver desembrulhar_assinatura_de_sistema. Mede quantos itens o
    # ajuste salvou de uma regeneracao por marcador.
    assinaturas_de_sistema_desembrulhadas: int = 0
    # Sintaxe Markdown tirada do corpo: links "[texto](url)" convertidos
    # em texto (o destino vai para `links`) e negritos "**x**".
    links_markdown_convertidos: int = 0
    negritos_markdown_removidos: int = 0
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
    # Pistas de dominio (typosquat, sender_domain_mismatch) inseridas
    # por construcao, nao autoanotadas pelo LLM nem pelo anotador as
    # cegas -- ver ResponseGenerator
    # ._completar_pistas_de_dominio_por_construcao. O artefato dessas
    # pistas fica no remetente ou num link, raramente citado de volta
    # no corpo, e o prompt pede evidencia como trecho do corpo -- no
    # piloto 5, 0 de 8 typosquats-alvo saíram autoanotados.
    cues_completadas_por_construcao: List[CueCode] = Field(default_factory=list)


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
            achados.extend(m.group(0) for m in _ENDERECO_DE_EXEMPLO.finditer(texto))
            achados.extend(m.group(0) for m in _NUMERO_MARCADOR.finditer(texto))
    return achados


def endereco_de_email(texto: Optional[str]) -> Optional[str]:
    """O endereco de e-mail contido no texto ("Nome <a@b.com>" ou
    "a@b.com"), ou None se nao houver.
    """
    if not texto:
        return None
    m = _EMAIL.search(texto)
    return m.group(0) if m else None


def _sem_acento(texto: str) -> str:
    decomposto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in decomposto if not unicodedata.combining(c))


def encontrar_nomes_de_instituicoes_reais(*textos: Optional[str]) -> List[str]:
    """Nomes e siglas de instituicoes reais (sem dominio -- ver
    `encontrar_dominios_reais`) em qualquer dos textos ("UFRJ",
    "Universidade Federal do Para", "Banco do Brasil"). Lista vazia =
    nada a corrigir.

    Separada de `encontrar_dominios_reais` pelo refinamento do piloto 5
    (item 15 do cabecalho deste arquivo): um NOME mencionado em texto
    corrido ("entregue pelos Correios" num cenario de logistica) e
    mencao legitima, nao personificacao -- so conta quando aparece onde
    a identidade de quem envia/recebe/aponta e de fato reivindicada
    (remetente, destinatario, links). Quem precisa do criterio antigo,
    sem distinguir campo, usa `encontrar_instituicoes_reais`.
    """
    achados: List[str] = []
    for texto in textos:
        if not texto:
            continue
        normalizado = _normalizar(texto)
        for padrao in (_INSTITUICAO_POR_TERMO, _INSTITUICAO_POR_ESTADO):
            achados.extend(m.group(0) for m in padrao.finditer(normalizado))
        achados.extend(m.group(0) for m in _SIGLA_MAIUSCULA.finditer(_sem_acento(texto)))
    return list(dict.fromkeys(achados))


def encontrar_dominios_reais(*textos: Optional[str]) -> List[str]:
    """Dominios de instituicoes reais ("receita.gov.br", "bb.com.br")
    em qualquer dos textos. Lista vazia = nada a corrigir.

    Ao contrario do nome (ver `encontrar_nomes_de_instituicoes_reais`),
    um dominio real escrito em QUALQUER campo -- inclusive o corpo -- e
    sempre personificacao: nao ha "mencao inocente" de um dominio real,
    porque, diferente de citar o nome de uma empresa em prosa, escrever
    o dominio e a propria forma de apontar para o endereco dela.
    """
    achados: List[str] = []
    for texto in textos:
        if not texto:
            continue
        achados.extend(m.group(0) for m in _DOMINIO_REAL.finditer(_normalizar(texto)))
    return list(dict.fromkeys(achados))


def encontrar_instituicoes_reais(*textos: Optional[str]) -> List[str]:
    """Nomes, siglas e dominios de instituicoes reais em qualquer dos
    textos ("UFRJ", "suporte@ufrj.edu.br", "Universidade Federal do
    Para", "receita.gov.br"), sem repeticao, sem distinguir campo --
    usada por `limpar_contexto_fundido` (o contexto fundido do RAG nao
    tem "campos": qualquer mencao a uma instituicao real ali e
    descartada). Lista vazia = nada a corrigir. O criterio da lista
    esta em instituicoes_reais.py.

    Para a checagem pos-geracao do item POR CAMPO (personificacao no
    remetente/dominio/links versus mencao no corpo/assunto -- piloto 5,
    ver cabecalho deste arquivo), use
    `encontrar_nomes_de_instituicoes_reais` e `encontrar_dominios_reais`
    separadamente.
    """
    achados: List[str] = []
    for texto in textos:
        achados.extend(encontrar_nomes_de_instituicoes_reais(texto))
        achados.extend(encontrar_dominios_reais(texto))
    return list(dict.fromkeys(achados))


def encontrar_dominios_caricatos(*textos: Optional[str]) -> List[str]:
    """Dominios (de endereco, link ou citados no corpo) que se denunciam
    sozinhos: "fake", "falso", "phishing", "golpe", "donotclick", "123"...
    Golpe real nao anuncia que e golpe no dominio. Lista vazia = nada a
    corrigir.
    """
    achados: List[str] = []
    for texto in textos:
        if not texto:
            continue
        for m in _DOMINIO.finditer(texto):
            dominio = m.group(0).casefold()
            if _DOMINIO_CARICATO.search(dominio):
                achados.append(dominio)
    return list(dict.fromkeys(achados))


def _problema_do_link(href: Optional[str]) -> Optional[str]:
    """Motivo pelo qual o destino de um link nao poderia existir num e-mail
    real, ou None. TLD/dominio reservado de exemplo, porta :0, ou href sem
    dominio plausivel (ver encontrar_links_invalidos)."""
    bruto = (href or "").strip()
    if not bruto:
        return "vazio"
    # Esquemas sem host (mailto:, tel:, sms:) sao links legitimos, nao "links
    # de exemplo" com dominio reservado: nao passam pelas checagens de TLD/porta
    # (senao "tel:+5591..." viraria porta invalida e forcaria regeneracao).
    esquema = bruto.split(":", 1)[0].lower() if ":" in bruto else ""
    if esquema in ("mailto", "tel", "sms"):
        return None
    # Sem esquema, urlsplit poe tudo no path (hostname vazio). Prefixa
    # "http://" so para extrair host/porta -- nao altera o link gerado.
    alvo = bruto if "://" in bruto else "http://" + bruto
    try:
        partes = urlsplit(alvo)
        host = (partes.hostname or "").lower()
        porta = partes.port  # levanta ValueError se fora de 0..65535
    except ValueError:
        return "malformado"
    if not host:
        return "sem_dominio"
    if porta == 0:
        return "porta_invalida"
    # IP cru (tecnica real de phishing) e valido -- so a porta foi checada.
    try:
        ipaddress.ip_address(host)
        return None
    except ValueError:
        pass
    rotulos = host.split(".")
    tld = rotulos[-1]
    if tld in _TLDS_RESERVADOS:
        return "tld_reservado"
    if len(rotulos) >= 2 and rotulos[-2] in _EXEMPLO_SEGUNDO_NIVEL and tld in _TLDS_DE_EXEMPLO:
        return "dominio_de_exemplo"
    if len(rotulos) < 2 or not tld.isalpha() or len(tld) < 2:
        return "sem_tld"
    return None


def encontrar_links_invalidos(links: Iterable["LinkRef"]) -> List[Tuple[str, str]]:
    """Links cujo destino (`href`) denuncia o e-mail como exemplo de
    laboratorio: TLD/dominio reservado (.example, .test, .invalid, example.com
    -- RFC 2606/6761), porta :0, ou href sem dominio plausivel (sem host, sem
    TLD). Da comparacao de modelos: "cbr-documentos.example",
    "confiarnacional.com.br:0". Devolve [(href, motivo)]; lista vazia = nada a
    corrigir. Vale para phishing E legitimo -- um link artificial estraga o
    item nos dois casos (o criterio nao depende do rotulo). IP cru e aceito.
    """
    achados: List[Tuple[str, str]] = []
    for link in links or ():
        href = getattr(link, "href", None)
        motivo = _problema_do_link(href)
        if motivo:
            achados.append((href or "", motivo))
    return achados


def encontrar_disclaimer_de_simulacao(*textos: Optional[str]) -> List[str]:
    """Trechos de meta-narracao "simulacao/conscientizacao/ficticio/nao e
    real" em qualquer dos textos (assunto, corpo, remetente, texto de link).
    Lista vazia = nada a corrigir.

    Phishing real nunca se anuncia como simulacao ou exercicio educativo;
    quando o gerador assa esse enquadramento no e-mail, o item vira inutil
    como exemplo (ver comentario de _DISCLAIMER_SIMULACAO). A deteccao vale
    para phishing e legitimo -- so o que importa e que o e-mail nao narre o
    proprio enquadramento; a analise fica no campo `explicacao`, a parte.
    """
    achados: List[str] = []
    for texto in textos:
        if not texto:
            continue
        achados.extend(m.group(0) for m in _DISCLAIMER_SIMULACAO.finditer(_normalizar(texto)))
    return list(dict.fromkeys(achados))


def normalizar_assunto(assunto: Optional[str]) -> str:
    """Assunto para comparacao de igualdade: sem acento, minusculas,
    espacos colapsados e sem pontuacao final.
    """
    return _normalizar(assunto or "").rstrip(" .:!?")


def converter_markdown(
    conteudo: str, links: Sequence[LinkRef]
) -> Tuple[str, List[LinkRef], int, int]:
    """Tira a sintaxe Markdown do corpo. "[texto](url)" vira so "texto" e,
    se o destino ainda nao estiver em `links`, entra la -- e assim que o
    especialista ve um link (lista a parte, texto exibido e destino).
    "**x**" vira "x". Devolve (corpo, links, links convertidos, negritos
    removidos).
    """
    novos_links = list(links)
    destinos = {link.href for link in novos_links}
    convertidos = 0

    def trocar(m: "re.Match[str]") -> str:
        nonlocal convertidos
        texto, destino = m.group(1).strip(), m.group(2)
        if destino not in destinos:
            novos_links.append(LinkRef(text=texto, href=destino))
            destinos.add(destino)
        convertidos += 1
        return texto

    conteudo = _LINK_MARKDOWN.sub(trocar, conteudo)
    conteudo, negritos = _NEGRITO_MARKDOWN.subn(r"\1", conteudo)
    return conteudo, novos_links, convertidos, negritos


def limpar_contexto_fundido(texto: str) -> Tuple[str, List[str]]:
    """Tira do contexto fundido do RAG (que vai igual para todos os itens
    do lote) as linhas que citam instituicao real e os trechos entre
    colchetes ou chaves ("[Seu Nome]"). Nomes de exemplo nao contam aqui:
    "Exemplo:" e comum num resumo de conhecimento. Devolve o texto limpo e
    o que foi tirado, para log.
    """
    removidos: List[str] = []
    linhas = []
    for linha in texto.split("\n"):
        if encontrar_instituicoes_reais(linha):
            removidos.append(linha.strip())
            continue
        for marcador in encontrar_marcadores(linha, nomes_genericos=False):
            linha = linha.replace(marcador, "")
            removidos.append(marcador)
        linhas.append(linha.rstrip())
    return "\n".join(linhas).strip(), removidos


def formula_proibida_no_assunto(assunto: Optional[str]) -> Optional[str]:
    """A formula "Acao Necessaria" (e variacoes) em qualquer posicao do
    assunto, ou None. Os 9 assuntos do piloto 2 comecavam com ela e, mesmo
    proibida no inicio, ela voltou no meio ("Protocolo #123456: Acao
    Necessaria sobre...").
    """
    if not assunto:
        return None
    m = _FORMULA_DE_ASSUNTO.search(_normalizar(assunto))
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


def desembrulhar_assinatura_de_sistema(
    remetente: Optional[str],
    assunto: Optional[str],
    conteudo: str,
    sigla: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str], str, int]:
    """Tira os colchetes de um rotulo de "notificacao de sistema" (cenario C)
    em CAIXA ALTA, nos tres lugares onde o modelo o coloca:

    - corpo: uma linha sozinha que e so o rotulo, sign-off ("[SISTEMA ANR]" ->
      "SISTEMA ANR"), tolerando um tracco/bullet de decoracao antes;
    - remetente: o rotulo no inicio, como nome de exibicao do sistema
      ("[SISTEMA CBR] <sistema@cbr...>" -> "SISTEMA CBR <sistema@cbr...>");
    - assunto: o rotulo no inicio, como tag ("[AVISO] ..." -> "AVISO ...").

    So desembrulha o que _e_rotulo_de_sistema aprova (palavra de sistema ou a
    `sigla` da instituicao): um placeholder em caixa alta ("[LINK]", "[SEU
    NOME]", "[DATA]", "[CLIQUE AQUI]") NAO e tocado e segue barrado por
    encontrar_marcadores. Devolve (remetente, assunto, corpo, n).

    Roda ANTES da checagem de marcador (ver ResponseGenerator): se o unico
    "marcador" era o rotulo de sistema, o item passa sem gastar uma regeneracao,
    e os campos finais ja ficam com o rotulo em texto corrido.
    """
    contador = [0]

    def _troca_linha(m: "re.Match[str]") -> str:
        if _e_rotulo_de_sistema(m.group(2), sigla):
            contador[0] += 1
            return f"{m.group(1)}{m.group(2)}{m.group(3)}"
        return m.group(0)

    def _troca_prefixo(m: "re.Match[str]") -> str:
        if _e_rotulo_de_sistema(m.group(2), sigla):
            contador[0] += 1
            return f"{m.group(1)}{m.group(2)}"
        return m.group(0)

    novo_conteudo = "\n".join(
        _ASSINATURA_LINHA.sub(_troca_linha, linha) for linha in conteudo.split("\n")
    )
    novo_remetente = (
        _ASSINATURA_PREFIXO.sub(_troca_prefixo, remetente, count=1) if remetente else remetente
    )
    novo_assunto = (
        _ASSINATURA_PREFIXO.sub(_troca_prefixo, assunto, count=1) if assunto else assunto
    )
    return novo_remetente, novo_assunto, novo_conteudo, contador[0]


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
