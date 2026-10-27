"""Sorteio da ficha de variacao por item (ver VariationSpec).

Sorteio BALANCEADO, nao independente: cada dimensao percorre a sua
lista inteira, embaralhada, antes de repetir um valor (`_Ciclo`). Num
lote de 50 itens medios isso garante que os 21 pares de pistas-alvo do
nivel aparecam de forma quase uniforme, em vez de deixar a sorte
concentrar o lote em poucos pares -- e a cobertura de pistas que o
protocolo de geracao pede.

Todas as listas abaixo sao genericas de proposito: o mesmo sorteador
atende os 5 eixos de contexto do protocolo, entao nenhum valor pode
pressupor um cenario especifico (universidade, banco, empresa). Elas
fixam DETALHES dentro do cenario pedido, nunca o trocam.
"""

import random
from itertools import combinations
from typing import Dict, List, Optional, Sequence, Tuple

from app.domain.models.cue import CueCode
from app.domain.models.variation_spec import VariationSpec

# Nomes brasileiros variados. "Joao", "Maria" e "Silva" ficam de fora de
# proposito: eram os valores-padrao do modelo no piloto ("Joao Silva",
# "Maria Silva", "Carlos Silva"), entao um item que voltar com eles e
# sinal de que o LLM ignorou a ficha.
PRIMEIROS_NOMES: Tuple[str, ...] = (
    "Ana", "Beatriz", "Camila", "Daniela", "Eduarda", "Fernanda", "Gabriela",
    "Helena", "Isabela", "Juliana", "Larissa", "Mariana", "Natália", "Paula",
    "Rafaela", "Sabrina", "Tatiane", "Vanessa", "Yasmin", "Letícia", "Josiane",
    "Keila", "Adriano", "Bruno", "Caio", "Diego", "Eduardo", "Felipe",
    "Gustavo", "Henrique", "Igor", "Jonas", "Lucas", "Marcelo", "Nicolas",
    "Otávio", "Pedro", "Rodrigo", "Samuel", "Thiago", "Vinícius", "Wesley",
    "Kauã", "Raimundo", "Edivaldo", "Railson",
)

SOBRENOMES: Tuple[str, ...] = (
    "Almeida", "Amaral", "Barbosa", "Brito", "Cardoso", "Carvalho", "Castro",
    "Correia", "Costa", "Dias", "Farias", "Ferreira", "Gomes", "Lima", "Lopes",
    "Machado", "Martins", "Melo", "Mendes", "Monteiro", "Moraes", "Nascimento",
    "Nogueira", "Oliveira", "Pereira", "Pinheiro", "Quaresma", "Ramos",
    "Ribeiro", "Rocha", "Santos", "Siqueira", "Sousa", "Tavares", "Teixeira",
    "Vasconcelos", "Vieira",
)

ASSINATURA_PESSOA = "uma pessoa com nome e cargo dentro da organização do cenário"
ASSINATURAS: Tuple[str, ...] = (
    "um setor ou departamento da organização do cenário, com assinatura "
    "institucional e sem nome de pessoa",
    ASSINATURA_PESSOA,
    "uma notificação automática de sistema da organização do cenário, sem "
    "pessoa e com tom de sistema",
    "um serviço terceirizado ou parceiro que atende a organização do cenário",
)

# Estilo do assunto (piloto 2: os 9 assuntos comecavam com "Acao
# Necessaria:", com dois pares identicos -- a ficha variava o corpo, nao
# o assunto).
ESTILOS_DE_ASSUNTO: Tuple[str, ...] = (
    "só o tema, curto, sem verbo no imperativo (ex.: 'Pendência no cadastro')",
    "com um número de protocolo ou de referência",
    "em forma de pergunta",
    "como notificação automática de sistema",
    "citando uma data ou um prazo",
    "citando o setor ou o serviço que envia",
)

# Como realizar cada pista-alvo no texto (piloto 2: pistas pedidas sem
# instrucao concreta viravam anotacao sem lastro -- typosquat com
# evidencia "Universidade Exemplo", scarcity com evidencia de prazo).
# Coerente com DEFINICOES_OPERACIONAIS (cue.py).
COMO_REALIZAR: Dict[CueCode, str] = {
    CueCode.URGENCY: "um prazo curto ou vago para agir, ou uma consequência iminente",
    CueCode.AUTHORITY: (
        "invocar uma autoridade (direção, órgão, chefia, norma ou sanção) para exigir a ação"
    ),
    CueCode.CREDENTIAL_REQUEST: (
        "pedir diretamente senha, código de verificação, dado de cartão ou login"
    ),
    CueCode.UNEXPECTED_ATTACHMENT: (
        "um anexo a abrir ou preencher, com nome de arquivo, que a pessoa não esperava"
    ),
    CueCode.SENDER_DOMAIN_MISMATCH: (
        "o nome exibido no remetente finge ser a organização, mas o endereço usa um domínio "
        "de e-mail gratuito ou de outra entidade"
    ),
    CueCode.TYPOSQUAT: (
        "um domínio que imita o da organização com um caractere trocado, a mais ou a menos "
        "(no endereço do remetente, ou no destino do link quando houver link)"
    ),
    CueCode.SCARCITY: (
        "quantidade ou oferta limitada (poucas vagas, só para os primeiros, benefício que "
        "acaba) -- não é prazo, prazo é urgency"
    ),
    CueCode.GENERIC_GREETING: "saudação genérica, sem nome de pessoa",
    CueCode.LINK_TEXT_MISMATCH: (
        "o texto do link sugere um destino oficial, mas o destino real (href) é outro domínio"
    ),
    CueCode.HOMOGLYPH: "um caractere visualmente parecido trocado num domínio ou nome",
}

ENDERECO_TYPOSQUAT = (
    "use um domínio que imita o da organização com um caractere trocado, a mais ou a menos"
)
ENDERECO_DOMINIO_ERRADO = (
    "o nome exibido finge ser a organização, mas o endereço usa um domínio de e-mail "
    "gratuito ou de outra entidade"
)
ENDERECO_PLAUSIVEL = (
    "use um domínio plausível da própria organização, sem erro de digitação: as pistas-alvo "
    "não incluem pista de domínio"
)
# Facil sem pista de dominio no alvo (piloto 3): "livre" puxava dominios
# caricatos ("universidade123", "donotclickhere"), ecoando o exemplo do
# prompt. O nivel pede remetente fora da organizacao, mas realista.
ENDERECO_LIVRE = (
    "um endereço claramente fora da organização, mas realista: e-mail gratuito (gmail, "
    "outlook, hotmail) com nome de setor, ou o domínio de uma empresa sem relação com o "
    "cenário"
)

ANGULOS_DE_PRETEXTO: Tuple[str, ...] = (
    "um documento ou comprovante que estaria faltando ou vencido",
    "um pagamento, taxa ou débito em aberto",
    "uma inconsistência ou divergência em dados cadastrais",
    "um prazo administrativo que estaria terminando",
    "uma mudança de sistema, migração ou atualização de cadastro ou acesso",
    "um bloqueio, suspensão ou restrição que poderia ser aplicada",
    "um valor, benefício ou reembolso a liberar",
)

# Acao pedida a vitima. Separada por presenca de link porque o prompt
# fixa a presenca de link por nivel (issue #20): MEDIO nunca tem link,
# FACIL e DIFICIL sempre tem.
ACOES_SEM_LINK: Tuple[str, ...] = (
    "responder ao próprio e-mail enviando dados ou um documento",
    "abrir e preencher um anexo",
    "ligar ou mandar mensagem para um número informado no corpo do e-mail",
    "enviar os dados para outro endereço de e-mail informado no corpo",
)
ACAO_ANEXO = ACOES_SEM_LINK[1]

ACOES_COM_LINK: Tuple[str, ...] = (
    "acessar o link para confirmar ou atualizar dados",
    "acessar o link para baixar ou visualizar um documento",
    "acessar o link para regularizar um pagamento",
    "acessar o link para entrar no sistema e resolver a pendência",
)

TONS: Tuple[str, ...] = (
    "formal e institucional",
    "cordial e próximo",
    "seco e burocrático",
    "prestativo, como quem quer ajudar a evitar um problema",
)

# FACIL pode ser curto; MEDIO e DIFICIL pedem paragrafos completos
# (VARIEDADE ESTRUTURAL do prompt, issue #20).
ESTRUTURAS_FACIL: Tuple[str, ...] = (
    "curto, um parágrafo só",
    "dois parágrafos curtos",
    "curto, com uma lista de itens ou passos",
)
ESTRUTURAS_COMPLETAS: Tuple[str, ...] = (
    "dois ou três parágrafos completos",
    "parágrafos completos com uma lista de itens ou passos",
    "parágrafos completos com um número de protocolo ou de referência",
)

ABERTURAS: Tuple[str, ...] = (
    "começar direto pelo assunto, sem frase de cortesia",
    "começar mencionando um evento ou uma data recente ligada ao cenário",
    "começar com quem escreve se apresentando e dizendo por que escreve",
    "começar com a saudação e uma frase curta de contexto",
)

# Pistas-alvo por nivel, coerentes com CARACTERISTICAS DOS NIVEIS DE
# DIFICULDADE do prompt de phishing:
# - FACIL: 3 pistas obvias, sempre com tratamento generico (o nivel pede
#   "ausencia de personalizacao"), entao `generic_greeting` e fixa e as
#   outras 2 saem do pool.
# - MEDIO: EXATAMENTE 2 pistas, sem link e com o nome do destinatario
#   ("personalizacao basica") -- por isso nenhuma pista de link e nem
#   `generic_greeting`. No piloto, a meta "exatamente 2" sem alvo
#   definido fazia o modelo completar a contagem com `generic_greeting`
#   em e-mails que tratavam o destinatario pelo nome.
# - DIFICIL: no maximo 1 pista, que o link obrigatorio ja consome
#   (issue #27: `typosquat` ou `sender_domain_mismatch`).
PISTA_FIXA_FACIL = CueCode.GENERIC_GREETING
POOL_FACIL: Tuple[CueCode, ...] = (
    CueCode.URGENCY,
    CueCode.AUTHORITY,
    CueCode.CREDENTIAL_REQUEST,
    CueCode.LINK_TEXT_MISMATCH,
    CueCode.TYPOSQUAT,
    CueCode.SENDER_DOMAIN_MISMATCH,
    CueCode.SCARCITY,
)
POOL_MEDIO: Tuple[CueCode, ...] = (
    CueCode.URGENCY,
    CueCode.AUTHORITY,
    CueCode.CREDENTIAL_REQUEST,
    CueCode.UNEXPECTED_ATTACHMENT,
    CueCode.SENDER_DOMAIN_MISMATCH,
    CueCode.TYPOSQUAT,
    CueCode.SCARCITY,
)
POOL_DIFICIL: Tuple[CueCode, ...] = (
    CueCode.TYPOSQUAT,
    CueCode.SENDER_DOMAIN_MISMATCH,
)


class _Ciclo:
    """Percorre `valores` embaralhados, sem repetir ate esgotar a lista;
    ai reembaralha e recomeca. E o que deixa o sorteio balanceado.
    """

    def __init__(self, valores: Sequence, rng: random.Random):
        self._valores = list(valores)
        self._rng = rng
        self._fila: List = []

    def proximo(self):
        if not self._fila:
            self._fila = list(self._valores)
            self._rng.shuffle(self._fila)
        return self._fila.pop()


class VariationSampler:
    """Sorteia uma ficha por item. Um sampler por lote: o estado dos
    ciclos e o que garante cobertura balanceada DENTRO do lote. Com a
    mesma `rng` semeada, a sequencia de fichas e reproduzivel.
    """

    def __init__(self, rng: Optional[random.Random] = None):
        self._rng = rng or random.Random()
        self._ciclos: Dict[str, _Ciclo] = {}

    def _proximo(self, chave: str, valores: Sequence):
        if chave not in self._ciclos:
            self._ciclos[chave] = _Ciclo(valores, self._rng)
        return self._ciclos[chave].proximo()

    def _nome(self) -> str:
        return f"{self._proximo('nome', PRIMEIROS_NOMES)} {self._proximo('sobrenome', SOBRENOMES)}"

    def _pistas_alvo(self, difficulty: str) -> List[CueCode]:
        if difficulty == "facil":
            par = self._proximo("pistas_facil", list(combinations(POOL_FACIL, 2)))
            return [PISTA_FIXA_FACIL, *par]
        if difficulty == "medio":
            return list(self._proximo("pistas_medio", list(combinations(POOL_MEDIO, 2))))
        if difficulty == "dificil":
            return [self._proximo("pistas_dificil", POOL_DIFICIL)]
        raise ValueError(f"dificuldade fora do vocabulario: '{difficulty}'")

    def sortear(self, difficulty: str, is_malicious: bool = True) -> VariationSpec:
        """`difficulty` ja normalizado ('facil' | 'medio' | 'dificil'),
        o mesmo valor que vai para o prompt.
        """
        if difficulty not in ("facil", "medio", "dificil"):
            raise ValueError(f"dificuldade fora do vocabulario: '{difficulty}'")

        estruturas = ESTRUTURAS_FACIL if difficulty == "facil" else ESTRUTURAS_COMPLETAS
        assinatura = self._proximo("assinatura", ASSINATURAS)
        comum = dict(
            assinatura=assinatura,
            nome_remetente=self._nome() if assinatura == ASSINATURA_PESSOA else None,
            estilo_assunto=self._proximo("estilo_assunto", ESTILOS_DE_ASSUNTO),
            angulo_pretexto=self._proximo("angulo", ANGULOS_DE_PRETEXTO),
            tom=self._proximo("tom", TONS),
            estrutura=self._proximo(f"estrutura_{difficulty}", estruturas),
            abertura=self._proximo("abertura", ABERTURAS),
        )

        if not is_malicious:
            # Item legitimo: sempre personalizado (sinal de confianca do
            # prompt legitimo), sem acao sorteada e sem pista; o
            # remetente e sempre da propria organizacao.
            return VariationSpec(
                nome_destinatario=self._nome(),
                endereco_remetente="use o domínio oficial da própria organização",
                **comum,
            )

        pistas = self._pistas_alvo(difficulty)
        if difficulty == "medio":
            # Pista de anexo pede uma acao coerente com ela.
            if CueCode.UNEXPECTED_ATTACHMENT in pistas:
                acao = ACAO_ANEXO
            else:
                acao = self._proximo("acao_sem_link", ACOES_SEM_LINK)
        else:
            acao = self._proximo("acao_com_link", ACOES_COM_LINK)

        nome = None if PISTA_FIXA_FACIL in pistas else self._nome()
        return VariationSpec(
            nome_destinatario=nome,
            endereco_remetente=_instrucao_de_endereco(difficulty, pistas),
            acao=acao,
            pistas_alvo=pistas,
            **comum,
        )


def _instrucao_de_endereco(difficulty: str, pistas: Sequence[CueCode]) -> str:
    """Dominio do remetente coerente com as pistas-alvo. No dificil, o
    typosquat vai no link obrigatorio, entao o remetente fica plausivel.
    No facil, sem pista de dominio no alvo, o nivel ja pede remetente
    fora da organizacao -- realista, nunca caricato (ENDERECO_LIVRE).
    """
    if CueCode.SENDER_DOMAIN_MISMATCH in pistas:
        if difficulty == "dificil":
            # O link obrigatorio do dificil iria para um typosquat por
            # padrao, criando uma 2a pista alem do orcamento de 1.
            return (
                ENDERECO_DOMINIO_ERRADO + "; o link obrigatório aponta para esse mesmo domínio, "
                "sem imitar o oficial com erro de digitação"
            )
        return ENDERECO_DOMINIO_ERRADO
    if CueCode.TYPOSQUAT in pistas and difficulty != "dificil":
        return ENDERECO_TYPOSQUAT
    if difficulty == "facil":
        return ENDERECO_LIVRE
    return ENDERECO_PLAUSIVEL


def renderizar_ficha(ficha: Optional[VariationSpec]) -> str:
    """Texto da ficha como entra no prompt (variavel `{variacao}`)."""
    if ficha is None:
        return (
            "Nenhuma ficha foi sorteada para este item: escolha os detalhes e as "
            "pistas livremente, respeitando a quantidade de pistas do nível "
            "(fácil: 3 ou mais; médio: exatamente 2; difícil: no máximo 1)."
        )

    if ficha.nome_destinatario:
        destinatario = (
            f"{ficha.nome_destinatario} -- use este nome na saudação e em `receptor`"
        )
    else:
        destinatario = (
            "sem nome -- a saudação deve ser genérica e adequada ao cenário "
            "(ex.: 'Prezado(a) cliente'), sem nenhum nome de pessoa"
        )

    quem_assina = ficha.assinatura
    if ficha.nome_remetente:
        quem_assina += f" -- o nome de quem assina é {ficha.nome_remetente}"
    linhas = [
        f"- Destinatário: {destinatario}",
        f"- Quem assina (na assinatura, no fim do corpo): {quem_assina}",
        f"- Endereço do remetente (`remetente`, sempre um e-mail): {ficha.endereco_remetente}",
        f"- Estilo do assunto: {ficha.estilo_assunto}",
        f"- Detalhe concreto do pretexto (dentro do cenário pedido, sem trocá-lo): "
        f"{ficha.angulo_pretexto}",
    ]
    if ficha.acao:
        linhas.append(f"- Ação pedida a quem recebe: {ficha.acao}")
    linhas += [
        f"- Tom: {ficha.tom}",
        f"- Estrutura do corpo: {ficha.estrutura}",
        f"- Abertura: {ficha.abertura}",
    ]
    if ficha.pistas_alvo:
        linhas.append("- Pistas-alvo (o e-mail deve conter cada uma, de forma reconhecível):")
        linhas.extend(
            f"    - `{p.value}`: {COMO_REALIZAR[p]}" for p in ficha.pistas_alvo
        )
    else:
        linhas.append("- Pistas-alvo: nenhuma (item legítimo)")
    return "\n".join(linhas)
