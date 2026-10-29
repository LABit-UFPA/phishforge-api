# app/domain/services/response_generator.py

import logging
from datetime import datetime
from typing import Callable, Dict, List, Optional

from langchain_core.prompts import PromptTemplate
from app.domain.models.channel_item_draft import (
    PhoneCallItemDraft,
    PixQrItemDraft,
    SmsItemDraft,
    WebsiteItemDraft,
    WhatsAppItemDraft,
)
from app.domain.models.cue import DEFINICOES_OPERACIONAIS, CampoDaPista, Cue, CueCode
from app.domain.models.difficulty import Difficulty
from app.domain.models.generated_item_draft import GeneratedItemDraft, ValidatedItemDraft
from app.domain.models.phish_scale import PhishScale, PremiseAlignment
from app.domain.models.variation_spec import VariationSpec
from app.domain.services.item_validation import (
    PISTAS_DE_DOMINIO,
    PistaRemovida,
    RelatorioValidacao,
    calcular_spans,
    converter_markdown,
    encontrar_dominios_caricatos,
    encontrar_dominios_reais,
    encontrar_marcadores,
    encontrar_nomes_de_instituicoes_reais,
    endereco_de_email,
    formula_proibida_no_assunto,
    limpar_contexto_fundido,
    registrar_aderencia,
    remover_assunto_repetido,
    remover_pistas_de_dominio_sem_dominio,
    remover_saudacao_generica_falsa,
)
from app.domain.services.llm_factory import (
    PROVIDER_OPENAI,
    build_chat_model,
    build_structured_llm,
)
from app.domain.services.variation_sampler import renderizar_ficha
from pydantic import BaseModel, Field

# Teto de tokens de saida das chamadas de geracao e de anotacao (piloto
# 5, item 2.5): sem teto, uma chamada que entra em repeticao estoura o
# contexto do modelo (16k tokens -- confirmado em 1 falha por piloto) e
# so falha DEPOIS de consumir a chamada inteira. Com o teto, a mesma
# chamada falha cedo e barato (JSON incompleto, erro do parser
# estruturado) em vez de no limite do modelo. Valores em
# app.core.config.Settings (MAX_TOKENS_GERACAO/MAX_TOKENS_ANOTACAO);
# aqui so os defaults para quem instancia a classe direto (testes).
_MAX_TOKENS_GERACAO_PADRAO = 2000
_MAX_TOKENS_ANOTACAO_PADRAO = 1000

# Data de hoje por extenso em portugues, sem depender de locale do
# sistema (piloto 5, item 2.6): um lote saiu com "15 de Outubro" ja no
# passado porque o prompt nunca dizia ao modelo qual e a data real --
# ele usava uma data tipica do proprio treinamento.
_MESES_PT = {
    1: "janeiro", 2: "fevereiro", 3: "março", 4: "abril", 5: "maio", 6: "junho",
    7: "julho", 8: "agosto", 9: "setembro", 10: "outubro", 11: "novembro", 12: "dezembro",
}


def _data_atual_por_extenso() -> str:
    agora = datetime.now()
    return f"{agora.day} de {_MESES_PT[agora.month]} de {agora.year}"


def _texto_da_resposta(response) -> str:
    """Texto plano de um AIMessage, seja qual for o provider.

    Na OpenAI `message.content` e uma str. Na Anthropic (sobretudo os
    modelos de reasoning) vem como LISTA de blocos -- p.ex.
    [{'type': 'thinking', ...}, {'type': 'text', 'text': '...'}] -- e um
    `.content.strip()` direto quebrava com "'list' object has no attribute
    'strip'", derrubando HyDE e a fusao de contexto para o fallback APENAS
    nos modelos Anthropic (RAG degradado so de um lado -> confundidor na
    comparacao de modelos). Aqui concatenamos os blocos de texto e
    ignoramos os de raciocinio.
    """
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        partes = []
        for bloco in content:
            if isinstance(bloco, str):
                partes.append(bloco)
            elif isinstance(bloco, dict):
                # blocos de texto da Anthropic/LangChain: {'type':'text','text':...}
                if bloco.get("type") == "text" and bloco.get("text"):
                    partes.append(bloco["text"])
                elif bloco.get("type") in (None, "output_text") and bloco.get("text"):
                    partes.append(bloco["text"])
            else:
                texto = getattr(bloco, "text", None)
                if texto:
                    partes.append(texto)
        return "".join(partes)
    return str(content or "")

# Versao do gerador de e-mail (prompts + validacoes), registrada em
# generation_jobs.run_metadata de cada lote. Mudar prompt ou validacao =
# mudar esta string, para os lotes de versoes diferentes nao se
# misturarem na analise.
VERSAO_GERADOR = "2026-10-28-piloto5"

# Quantas vezes gerar o item de novo quando ele volta estruturalmente
# invalido (marcador de template, remetente ou destinatario sem e-mail,
# instituicao real, dominio caricato, "Acao Necessaria" no assunto). Esgotado,
# generate_response levanta ItemInvalidoError (falha de geracao, nao
# descarte por duplicidade).
MAX_REGENERACOES_POR_MARCADOR = 2


# Campo de RelatorioValidacao incrementado a cada regeneracao, por motivo
# devolvido por ResponseGenerator._problema_estrutural.
_CONTADOR_POR_MOTIVO = {
    "marcador": "regeneracoes_por_marcador",
    "remetente_sem_email": "regeneracoes_por_remetente",
    "destinatario_sem_email": "regeneracoes_por_destinatario",
    "instituicao_real": "regeneracoes_por_instituicao_real",
    "dominio_caricato": "regeneracoes_por_dominio_caricato",
    "assunto_proibido": "regeneracoes_por_assunto",
}


class ItemInvalidoError(Exception):
    """Item gerado que nao pode ser usado mesmo depois das
    regeneracoes (marcador de template, remetente ou destinatario sem
    e-mail, instituicao real, dominio caricato ou formula proibida no
    assunto).
    """


# Definicao de cada codigo, injetada nos prompts (issue #5, passo 3):
# sem isso, o `Enum` do structured output so impede o modelo de INVENTAR
# um codigo -- nao ajuda a ESCOLHER o codigo certo. Desde o piloto 2, e o
# mesmo texto que o especialista ve (DEFINICOES_OPERACIONAIS).
_TAXONOMIA_DE_PISTAS = "\n".join(
    f"- {code.value}: {definicao}" for code, definicao in DEFINICOES_OPERACIONAIS.items()
)


class PistaAnotada(BaseModel):
    """Uma pista encontrada pelo anotador as cegas."""

    code: CueCode
    campo: CampoDaPista = Field(
        description="Onde a evidencia esta: remetente, assunto ou conteudo."
    )
    evidencia: str = Field(
        description="Trecho copiado literalmente do campo indicado, sem aspas."
    )


class AnotacaoCega(BaseModel):
    """Saida do anotador as cegas (piloto 2, 27/10/2026)."""

    pistas: List[PistaAnotada] = Field(default_factory=list)
    premise_alignment: PremiseAlignment


# Regras de forma comuns aos dois prompts de e-mail (piloto 2, 27/10/2026):
# remetente sem endereco em 4 de 9 itens, "[Informacoes de Contato]" e
# "Universidade Exemplo" no texto, os 9 assuntos com "Acao Necessaria:".
# Sem chaves literais no texto: e inserido num PromptTemplate.
#
# A identidade da organizacao (piloto 5, item 2.1) deixou de pedir ao
# LLM para "inventar um nome ficticio": essa instrucao -- repetida 3x
# com a palavra "ficticia/o" -- era a causa de 22 das 25 falhas do
# piloto 4 (o modelo escrevia "Universidade Fictícia" ao pe da letra, o
# validador barrava e mandava gerar de novo com a MESMA instrucao).
# Agora a identidade vem pronta na ficha (ver VariationSampler e
# instituicoes_ficticias.py) e o LLM so a usa.
_REGRAS_DE_FORMA = (
    "### REGRAS DE FORMA (OBRIGATÓRIO)\n"
    "- `remetente` é SEMPRE um endereço de e-mail, opcionalmente com nome de exibição "
    "no formato 'Nome Exibido <endereco@dominio>'. Quem assina, da ficha, aparece na "
    "assinatura no fim do `conteudo`; não substitui o endereço.\n"
    "- O domínio do endereço do remetente segue a linha 'Endereço do remetente' da ficha.\n"
    "- `receptor` é SEMPRE o endereço de e-mail de quem recebe -- use EXATAMENTE o "
    "endereço indicado na ficha, nunca um endereço inventado (com o nome da ficha na "
    "frente, se houver: 'Nome <endereco@dominio>'), nunca uma saudação nem um grupo como "
    "'Prezados Alunos'. A saudação vai na primeira linha do `conteudo`.\n"
    "- Domínios e endereços são realistas: nunca domínios que se denunciam sozinhos, com "
    "'fake', 'falso', 'phishing', 'golpe', 'donotclick', '123' ou parecidos.\n"
    "- `conteudo` é texto simples, sem Markdown: nada de [texto](url) nem **negrito**. Um "
    "link aparece no corpo só pelo texto exibido; o destino fica em `links`.\n"
    "- A identidade da organização já vem pronta na FICHA DO ITEM (nome-base, sigla e "
    "domínio oficial): combine o nome-base com o tipo de organização que o CENÁRIO pede "
    "(ex.: nome-base 'Vallonta' + cenário de universidade -> 'Universidade Vallonta'; mesmo "
    "nome-base + cenário de banco -> 'Banco Vallonta') e use esse nome, essa sigla e esse "
    "domínio em TODO o e-mail. Nunca invente outro nome, sigla ou domínio para a "
    "organização, e nunca use nome, sigla ou domínio de uma instituição real (universidade, "
    "banco, órgão público, empresa) em nenhuma parte do e-mail, mesmo que o cenário cite "
    "uma.\n"
    "- Nunca escreva texto entre colchetes ou entre chaves: todo dado do e-mail (nome, "
    "telefone, protocolo, contato) aparece preenchido, inventado quando preciso. Nunca use "
    "a sequência '123456' como número de exemplo (protocolo, pedido, código): é um "
    "placeholder reconhecível, não um número de verdade.\n"
    "- Siga o estilo de assunto da ficha. Nunca use 'Ação Necessária' ou 'Ação Requerida' "
    "(nem variações) em nenhuma parte do assunto, e não repita o assunto como primeira "
    "linha do `conteudo`.\n\n"
)


def _links_para_anotador(links) -> str:
    if not links:
        return "(nenhum)"
    return "\n".join(f"- texto exibido: {link.text} | destino real: {link.href}" for link in links)


def _construir_prompt_canal(
    instrucao_sistema: str, regras_do_canal: str, niveis_dificuldade: str, campos: str
) -> str:
    """Monta o prompt de um canal novo (issue #6) na mesma estrutura
    do prompt de email (instrucao -> contexto -> tarefa -> regras do
    meio -> niveis -> formato), mas mais enxuto: os 3 canais novos nao
    tem `cues`/`premise_alignment` (adaptar a taxonomia por canal e
    decisao de pesquisa fora do escopo desta entrega, ver comentario
    da issue #6), entao nao precisam da secao Chain-of-Thought inteira
    que o email tem para blindar esses dois campos extras.
    """
    return (
        "## 1. INSTRUÇÃO DE SISTEMA\n"
        f"{instrucao_sistema}\n\n"
        "## 2. CONTEXTO RECUPERADO\n"
        "**CONHECIMENTO ACADÊMICO DA BASE VETORIAL:**\n"
        "{relevant_docs}\n\n"
        "## 3. ESPECIFICAÇÃO DA TAREFA\n"
        "**Nível de Dificuldade:** {difficulty}\n"
        "**Cenário Específico:** {context}\n\n"
        f"{regras_do_canal}\n\n"
        f"{niveis_dificuldade}\n\n"
        "## FORMATO DE RESPOSTA\n"
        f"Gere APENAS o objeto JSON com os campos solicitados ({campos}).\n"
    )


# Regras de realismo e niveis de dificuldade por canal (issue #6).
# Cada uma serve DOIS prompts (malicioso e legitimo) do mesmo canal --
# so a INSTRUÇÃO DE SISTEMA muda de objetivo entre os dois, igual ao
# padrao ja estabelecido para email (#3).

_REGRAS_WEBSITE = (
    "### O QUE TORNA UM SITE FALSO CONVINCENTE (OBRIGATÓRIO)\n"
    "- `url`: domínio parecido com o legítimo (typosquatting, subdomínio enganoso, TLD "
    "trocado) -- nunca o domínio oficial exato\n"
    "- `title` e `visible_content` devem imitar o layout/tom de uma página real do "
    "cenário pedido (login, confirmação, prêmio, atualização cadastral)\n"
    "- `visible_content` é o que a vítima LÊ na página -- não é um email, não tem "
    "saudação nem assinatura de remetente\n\n"
    "### NÍVEIS DE DIFICULDADE\n"
    "**FÁCIL:** domínio visivelmente errado, página com erros visuais/gramaticais óbvios.\n"
    "**MÉDIO:** domínio parecido mas com uma inconsistência perceptível, layout razoável.\n"
    "**DIFÍCIL:** domínio quase idêntico ao original, página visualmente indistinguível "
    "da legítima."
)

_REGRAS_WEBSITE_LEGITIMO = (
    "### O QUE TORNA A PÁGINA LEGÍTIMA (OBRIGATÓRIO)\n"
    "- `url` é o domínio OFICIAL e coerente com a organização do cenário\n"
    "- NUNCA pede senha, código de verificação ou dado de cartão fora de um fluxo já "
    "esperado pelo usuário\n"
    "- `visible_content` tem tom institucional, sem urgência artificial\n\n"
    "### NÍVEIS DE DIFICULDADE (risco de falso alarme)\n"
    "**FÁCIL:** sinais de confiança óbvios (domínio oficial claro, nenhuma urgência).\n"
    "**MÉDIO:** legítimo mas com algum elemento que poderia gerar dúvida à primeira vista.\n"
    "**DIFÍCIL:** legítimo mas com elemento que superficialmente lembra golpe (prazo "
    "real apertado), exigindo checar o domínio para não cair em falso alarme."
)

_REGRAS_PHONE_CALL = (
    "### O QUE TORNA UMA LIGAÇÃO CONVINCENTE (OBRIGATÓRIO)\n"
    "- Sem elemento visual: toda tática é VERBAL -- tom de voz (na transcrição, via "
    "escolha de palavras), pressa, autoridade fingida, pedido de código recebido por "
    "SMS\n"
    "- `caller` é o número/identificação exibida (spoofed) na tela do telefone\n"
    "- `transcript` é o roteiro falado pelo golpista, em primeira pessoa, como se "
    "estivesse sendo dito\n\n"
    "### NÍVEIS DE DIFICULDADE\n"
    "**FÁCIL:** pressa óbvia e explícita, ameaça direta, roteiro decorado e artificial.\n"
    "**MÉDIO:** tom profissional mas com pequena inconsistência no roteiro.\n"
    "**DIFÍCIL:** roteiro fluido e contextualmente coerente com a rotina do alvo, "
    "pressão sutil."
)

_REGRAS_PHONE_CALL_LEGITIMO = (
    "### O QUE TORNA A LIGAÇÃO LEGÍTIMA (OBRIGATÓRIO)\n"
    "- NUNCA pede código de SMS, senha ou dado de cartão completo por telefone\n"
    "- Oferece um canal alternativo verificável (ligar de volta pelo número oficial)\n"
    "- Tom institucional, sem pressa artificial\n\n"
    "### NÍVEIS DE DIFICULDADE (risco de falso alarme)\n"
    "**FÁCIL:** tom calmo, nenhuma solicitação sensível, encerramento tranquilo.\n"
    "**MÉDIO:** legítimo mas com um pedido de confirmação que poderia soar estranho.\n"
    "**DIFÍCIL:** legítimo mas com prazo real apertado, exigindo notar a ausência de "
    "pedido de credencial para não desconfiar à toa."
)

_REGRAS_PIX_QR = (
    "### O QUE TORNA UM GOLPE DE PIX/QR CONVINCENTE (OBRIGATÓRIO)\n"
    "- Não há domínio nem link nesse canal -- a pista central é `recipient` (nome do "
    "recebedor) divergente do esperado pelo cenário, ou um `pix_key` que não bate com "
    "a organização alegada\n"
    "- `amount` é sempre string (ex.: '149.90'), nunca número\n"
    "- Cenários típicos: cobrança falsa, QR trocado em ponto físico, 'devolução' de "
    "valor pago a mais\n\n"
    "### NÍVEIS DE DIFICULDADE\n"
    "**FÁCIL:** `recipient` obviamente não relacionado ao cenário, valor incoerente.\n"
    "**MÉDIO:** `recipient` parecido mas com pequena inconsistência de nome/razão social.\n"
    "**DIFÍCIL:** `recipient` plausível para o cenário, só a `pix_key` denuncia o golpe."
)

_REGRAS_PIX_QR_LEGITIMO = (
    "### O QUE TORNA A COBRANÇA PIX LEGÍTIMA (OBRIGATÓRIO)\n"
    "- `recipient` é exatamente a organização/pessoa esperada pelo cenário\n"
    "- `amount` condizente com o que o cenário descreve, sem valor arredondado suspeito\n"
    "- Nenhuma urgência artificial para pagar\n\n"
    "### NÍVEIS DE DIFICULDADE (risco de falso alarme)\n"
    "**FÁCIL:** recebedor e valor obviamente corretos e esperados.\n"
    "**MÉDIO:** legítimo mas com um valor um pouco diferente do usual, sem ser suspeito.\n"
    "**DIFÍCIL:** legítimo mas com timing incomum (cobrança fora do ciclo esperado), "
    "exigindo conferir o recebedor para não desconfiar à toa."
)

# SMS/WhatsApp (issue #6, desbloqueados pela phishing-quest-api #68: os
# dois shapes exigem valor aninhado -- `links`/`messages` como array de
# objetos -- que o buildDraftContent do Go so passou a aceitar depois
# daquela issue).

_REGRAS_SMS = (
    "### O QUE TORNA UM SMS DE GOLPE CONVINCENTE (OBRIGATÓRIO)\n"
    "- `text` é CURTO (poucas linhas) e SEM campo de assunto -- SMS não tem assunto\n"
    "- `sender` costuma ser um número curto ou alfanumérico (nunca um endereço de email)\n"
    "- Links, quando presentes em `text`, tipicamente aparecem encurtados -- isso pesa a "
    "favor da pista `link_text_mismatch`, já que o texto exibido não revela o domínio real\n"
    "- Golpe de SMS depende mais de urgência e menos de personalização/formatação (não há "
    "layout num SMS)\n\n"
    "### NÍVEIS DE DIFICULDADE\n"
    "**FÁCIL:** urgência exagerada e óbvia, remetente claramente estranho, link visivelmente "
    "suspeito.\n"
    "**MÉDIO:** remetente plausível (ex.: nome de transportadora/banco), pretexto comum "
    "(entrega, fatura), link encurtado sem outro sinal de alarme.\n"
    "**DIFÍCIL:** pretexto muito específico e oportuno (rastreamento real esperado pela "
    "vítima), sem erro de português, link encurtado indistinguível de um legítimo."
)

_REGRAS_SMS_LEGITIMO = (
    "### O QUE TORNA O SMS LEGÍTIMO (OBRIGATÓRIO)\n"
    "- NUNCA pede senha, código de verificação ou dado de cartão\n"
    "- Se houver link, ele é coerente com a organização (`text` e `href` não divergem)\n"
    "- Tom institucional, direto, sem ameaça\n\n"
    "### NÍVEIS DE DIFICULDADE (risco de falso alarme)\n"
    "**FÁCIL:** remetente e conteúdo obviamente esperados (ex.: código de entrega que a "
    "pessoa já aguardava).\n"
    "**MÉDIO:** legítimo mas com timing um pouco inesperado.\n"
    "**DIFÍCIL:** legítimo mas com urgência real (ex.: prazo de hoje), exigindo notar a "
    "ausência de pedido de credencial para não desconfiar à toa."
)

_REGRAS_WHATSAPP = (
    "### O QUE TORNA UMA CONVERSA DE WHATSAPP CONVINCENTE (OBRIGATÓRIO)\n"
    "- `messages` é um HISTÓRICO (2 a 4 mensagens), não uma mensagem solta -- simule contato "
    "inicial, uma resposta a uma dúvida ou objeção, e pressão final, por exemplo\n"
    "- `author` de cada mensagem é `contact` (o golpista/organização simulada) ou `user` "
    "(uma reação plausível do destinatário) -- variar entre os dois torna o histórico mais "
    "realista que uma sequência de mensagens todas do mesmo lado\n"
    "- `display_name` e tom coloquial são o vetor de confiança aqui (não há domínio nem "
    "assinatura formal como em email)\n"
    "- Se houver link dentro do texto de uma mensagem, ele reforça a pista "
    "`link_text_mismatch` quando o texto ao redor do link sugere um destino diferente do "
    "real\n\n"
    "### NÍVEIS DE DIFICULDADE\n"
    "**FÁCIL:** `display_name` genérico ou suspeito, pressa óbvia, poucas trocas.\n"
    "**MÉDIO:** `display_name` parecido com um contato real, alguma inconsistência no tom.\n"
    "**DIFÍCIL:** `display_name` e histórico indistinguíveis de uma conversa real, pressão "
    "sutil ao longo das mensagens."
)

_REGRAS_WHATSAPP_LEGITIMO = (
    "### O QUE TORNA A CONVERSA LEGÍTIMA (OBRIGATÓRIO)\n"
    "- NUNCA pede código recebido por SMS, senha ou dado de cartão\n"
    "- `display_name` corresponde de fato à organização/pessoa esperada pelo cenário\n"
    "- Tom institucional ou pessoal coerente com o cenário, sem pressa artificial\n\n"
    "### NÍVEIS DE DIFICULDADE (risco de falso alarme)\n"
    "**FÁCIL:** histórico claramente esperado pelo destinatário, sem nenhum pedido sensível.\n"
    "**MÉDIO:** legítimo mas com uma pergunta que poderia soar estranha à primeira vista.\n"
    "**DIFÍCIL:** legítimo mas com timing incomum, exigindo notar a ausência de pedido de "
    "credencial para não desconfiar à toa."
)


class ResponseGenerator:
    def __init__(
        self,
        api_key: str,
        model_name: str = "gpt-4o-mini",
        temperature: Optional[float] = 0.7,
        anotacao_cega: bool = False,
        max_tokens_geracao: int = _MAX_TOKENS_GERACAO_PADRAO,
        max_tokens_anotacao: int = _MAX_TOKENS_ANOTACAO_PADRAO,
        provider: str = PROVIDER_OPENAI,
        anthropic_api_key: str = "",
        seed: Optional[int] = None,
    ):
        # Guardados para o lote registrar com que modelo/temperatura os
        # itens foram gerados (generation_jobs.run_metadata).
        self.model_name = model_name
        self.temperature = temperature
        self.provider = provider
        # `api_key` e a chave OpenAI (nome mantido para nao quebrar os
        # chamadores e testes antigos, que passam so `api_key=`). Com
        # provider=anthropic, o LLM de geracao usa `anthropic_api_key`;
        # a chave OpenAI segue valendo para quem precisar (embedding).
        # Todas as chains de geracao (anotacao, item, HyDE/fusao via
        # text_llm e os 5 canais) passam pelo mesmo provider -- ver
        # llm_factory.build_chat_model.
        #
        # `temperature=None` => modelo de reasoning (OpenAI o-series e
        # alguns GPT-5), que rejeita `temperature != 1`. Nesse modo
        # TODAS as sub-chains omitem temperature (inclusive as que
        # usariam 0.0/0.2): `_temp` abaixo zera o valor fixo quando a
        # temperatura base e None, para o item comparavel na avaliacao
        # nao quebrar na chamada.
        modo_reasoning = temperature is None

        def _temp(valor_fixo):
            return None if modo_reasoning else valor_fixo

        # `seed`: reprodutibilidade best-effort na OpenAI (ignorado na
        # Anthropic -- ver build_chat_model). Vale para TODAS as sub-chains
        # (item, anotacao, HyDE/fusao via text_llm e os 5 canais), ja que
        # todas sao construidas por este `_chat`. Default None => geracao
        # de producao segue sem seed, como antes.
        def _chat(temperatura, max_tokens=None):
            return build_chat_model(
                provider,
                model_name,
                openai_api_key=api_key,
                anthropic_api_key=anthropic_api_key,
                temperature=temperatura,
                max_tokens=max_tokens,
                seed=seed,
            )

        self._chat = _chat

        # Saida estruturada. OpenAI: with_structured_output nativo. Anthropic:
        # instructor em JSON-mode (sem tool_choice, sem thinking), porque
        # nenhum caminho de saida estruturada do langchain-anthropic 0.3.18 e
        # confiavel com os Claude 5.5 de reasoning (ver build_structured_llm).
        # Para Anthropic, build_structured_llm ignora a temperatura (recusada).
        # Todas as chains estruturadas abaixo (item, anotacao e os 5 canais)
        # passam por aqui.
        def _structured(schema, temperatura, max_tokens=None):
            return build_structured_llm(
                provider,
                model_name,
                schema,
                openai_api_key=api_key,
                anthropic_api_key=anthropic_api_key,
                temperature=temperatura,
                max_tokens=max_tokens,
                seed=seed,
            )
        # Piloto 2: com o gerador anotando as proprias pistas sabendo as
        # pistas-alvo, as anotadas coincidiram 100% com o alvo mesmo
        # quando o texto nao as sustentava. Ligado, `cues` e
        # `premise_alignment` passam a vir de uma 2a chamada que so ve o
        # item pronto. Default False aqui (testes antigos); o container
        # liga pelo config (ANOTACAO_CEGA).
        self.anotacao_cega = anotacao_cega
        self.annotation_llm = _structured(AnotacaoCega, _temp(0.0), max_tokens_anotacao)
        self.llm = _structured(GeneratedItemDraft, temperature, max_tokens_geracao)

        self.text_llm = _chat(_temp(0.2))

        self.prompt_template = PromptTemplate(
            input_variables=["context", "difficulty", "relevant_docs", "variacao", "data_atual"],
            template=(
                "## 1. INSTRUÇÃO DE SISTEMA\n"
                "Você é um especialista em cibersegurança especializado na criação de emails de phishing educacionais baseados em pesquisas acadêmicas.\n\n"

                "## 2. CONTEXTO RECUPERADO\n"
                "**CONHECIMENTO ACADÊMICO DA BASE VETORIAL:**\n"
                "{relevant_docs}\n\n"

                "## 3. ESPECIFICAÇÃO DA TAREFA\n"
                "**Nível de Dificuldade:** {difficulty}\n"
                "**Cenário Específico:** {context}\n"
                "**Data de hoje:** {data_atual} -- use-a para qualquer data ou prazo que o "
                "e-mail mencionar (nunca uma data do passado por engano; prazo de urgência "
                "continua podendo ser vago, mas se citar uma data concreta, ela é relativa a "
                "hoje).\n\n"

                "### FICHA DO ITEM (OBRIGATÓRIO -- sorteada pelo sistema para este item)\n"
                "Cada chamada sua é independente e não sabe o que as outras geraram (ver "
                "VARIEDADE ESTRUTURAL abaixo); sem a ficha, itens do mesmo cenário saem como "
                "cópias uns dos outros -- foi o que um lote-piloto real mostrou. Por isso o "
                "sistema sorteia, para cada item, os detalhes abaixo. Siga a ficha à risca: ela "
                "fixa DETALHES dentro do cenário pedido, nunca troca o cenário. As pistas-alvo "
                "da ficha definem QUAIS pistas da taxonomia o e-mail deve conter.\n"
                "{variacao}\n\n"
                "Nunca abra o e-mail com fórmulas prontas como 'Esperamos que você esteja bem' "
                "ou 'Espero que esta mensagem o encontre bem'. Nunca deixe marcadores de "
                "template no texto, como [Nome] ou [Nome do Estudante]: use exatamente o nome "
                "da ficha, ou uma saudação genérica quando a ficha disser que não há nome.\n\n"
                f"{_REGRAS_DE_FORMA}"

                "### VARIEDADE ESTRUTURAL (OBRIGATÓRIO -- validado empiricamente na issue #20)\n"
                "Uma checagem contra geração real mostrou dois problemas que já foram "
                "corrigidos por instruções mais concretas: (1) pedir 'variedade' de forma "
                "abstrata não funciona -- cada chamada sua é independente e não sabe o que "
                "outras chamadas geraram, então a presença de link segue a REGRA FIXA por "
                "nível de dificuldade descrita em CARACTERÍSTICAS DOS NÍVEIS DE DIFICULDADE "
                "abaixo, não uma escolha livre sua; (2) comprimento também varia por nível -- "
                "nem todo phishing é curto: em MÉDIO/DIFÍCIL, escreva parágrafos completos e "
                "tom institucional elaborado, do mesmo tamanho que uma comunicação legítima "
                "real teria.\n"
                "Urgência/prazo ('imediatamente', 'urgente', prazo curto) é uma TÁTICA "
                "PSICOLÓGICA, não uma característica textual reservada ao phishing -- "
                "comunicações legítimas também mencionam prazos reais (data de vencimento, "
                "por exemplo). O que diferencia o golpe não é a MENÇÃO a um prazo, mas a "
                "AUSÊNCIA de verificação possível: aqui, ao usar urgência, garanta que o "
                "prazo seja vago ou artificialmente curto, não uma data verificável.\n\n"

                "### CARACTERÍSTICAS DOS NÍVEIS DE DIFICULDADE\n\n"
                
                "**FÁCIL:**\n"
                "- Remetente claramente fora da organização, mas realista: um e-mail gratuito "
                "(gmail, outlook, hotmail) com nome de setor, ou o domínio de uma empresa sem "
                "relação com o cenário\n"
                "- Assunto com erros ortográficos ou gramaticais evidentes\n"
                "- Urgência exagerada e óbvia ('URGENTE!!!', 'AÇÃO IMEDIATA')\n"
                "- LINK OBRIGATÓRIO: inclua um link visivelmente suspeito ou encurtado em "
                "`links` (regra fixa deste nível, não uma escolha -- issue #20)\n"
                "- Formatação inconsistente ou amadora\n"
                "- Ausência de personalização (tratamento genérico)\n"
                "- Ameaças diretas e explícitas\n"
                "- Solicitação óbvia de informações sensíveis\n"
                "- Phish Scale: inclua as 3 pistas-alvo da FICHA DO ITEM, óbvias (pode haver "
                "mais, nunca menos), e premissa `baixo` ou `medio` (pretexto genérico, sem "
                "relação com a rotina específica de quem recebe)\n\n"

                "**MÉDIO:**\n"
                "- Remetente parcialmente convincente mas com pequenas inconsistências\n"
                "- Assunto plausível mas com alguns indicadores de suspeita\n"
                "- Urgência moderada com justificativa aparente\n"
                "- SEM LINK OBRIGATÓRIO: `links` deve ser `[]` neste nível (regra fixa -- "
                "issue #20) -- peça os dados por resposta direta ao e-mail, por anexo, ou "
                "peça uma ligação para um número informado no próprio corpo\n"
                "- Formatação mais profissional, similar a comunicações empresariais\n"
                "- Personalização básica (o nome do destinatário que está na ficha)\n"
                "- Mistura de informações verdadeiras com falsas\n"
                "- Uso de logos e identidade visual parcialmente convincentes\n"
                "- Solicitação indireta de ação (download, clique, verificação)\n"
                "- Phish Scale: EXATAMENTE as 2 pistas-alvo da FICHA DO ITEM, moderadas, e "
                "premissa `medio`. Não acrescente outras pistas da taxonomia: com nome na "
                "saudação, `generic_greeting` não está presente\n\n"

                "**DIFÍCIL:**\n"
                "- Remetente altamente convincente, indistinguível de comunicações legítimas\n"
                "- Assunto contextualmente perfeito e relevante\n"
                "- Formatação profissional idêntica às comunicações oficiais\n"
                "- Personalização avançada (cargo, projetos específicos, colegas)\n"
                "- Informações específicas e verificáveis sobre a empresa/pessoa\n"
                "- Identidade visual perfeita (logos, assinaturas, layout)\n"
                "- Contexto temporal relevante (eventos atuais, datas importantes)\n"
                "- LINK OBRIGATÓRIO: inclua um link com domínio similar ao original "
                "(typosquatting sutil) em `links` (regra fixa deste nível -- issue #20)\n"
                "- Phish Scale: mire em NO MÁXIMO 1 pista no total (validado empiricamente na "
                "issue #27 -- rodadas anteriores erravam por tratar sofisticação como 'muitos "
                "elementos convincentes', o que gerava 2+ pistas contáveis). O link obrigatório "
                "acima JÁ CONSOME esse orçamento com a pista-alvo da FICHA DO ITEM "
                "(`typosquat` ou `sender_domain_mismatch`) -- os itens da lista acima (remetente, assunto, "
                "formatação, personalização, identidade visual, contexto temporal) são "
                "elementos de REALISMO, não pistas da taxonomia, e não devem virar entradas em "
                "`cues`. NÃO anote `urgency` nem `authority` neste nível: se usar algum apelo "
                "de autoridade/urgência, ele precisa ser tão sutil que nem o próprio golpista "
                "chamaria de tática -- mais perto de tom profissional comum do que de "
                "engenharia social explícita. Premissa `alto` -- o "
                "pretexto precisa parecer parte genuína da rotina de quem recebe, dado o "
                "cenário '{context}'\n\n"

                "## 3.5 TAXONOMIA DE PISTAS (cues) -- ISSUE #5\n"
                "Alem do texto, anote em `cues` QUAIS das pistas abaixo estao de fato "
                "presentes no email que voce esta escrevendo. Use SOMENTE estes 10 codigos "
                "(nunca invente um novo):\n"
                f"{_TAXONOMIA_DE_PISTAS}\n\n"
                "Para cada pista, informe `evidencia`: o TRECHO LITERAL do `conteudo` que "
                "comprova a pista (copie exatamente, sem aspas, nao parafraseie -- isso sera "
                "conferido). Deixe `span_start`/`span_end` como null: as posicoes sao "
                "calculadas pelo sistema a partir da `evidencia`, e por isso ela precisa ser "
                "um trecho copiado do `conteudo`. So anote pistas REALMENTE presentes: uma "
                "lista vazia e melhor que uma pista forcada. As pistas-alvo da FICHA DO ITEM "
                "devem estar no texto, mas anote o que voce de fato escreveu. "
                "`generic_greeting` so se aplica quando a saudacao for de fato generica "
                "('Prezado cliente'), nao quando houver qualquer personalizacao.\n\n"

                "## 3.6 ALINHAMENTO DE PREMISSA (premise_alignment) -- ISSUE #9\n"
                "Alem de escrever o email, julgue o proprio `premise_alignment`: o quanto o "
                "PRETEXTO que voce usou se encaixa na rotina de quem recebe, dado o cenario "
                "'{context}'. Nao e sobre quao bem escrito esta o email -- e sobre se o "
                "MOTIVO do email faz sentido para o dia a dia da pessoa:\n"
                "- `alto`: o pretexto e algo que faz parte da rotina de quem recebe (fatura "
                "de um servico que a pessoa realmente usa, processo interno que existe na "
                "empresa do cenario)\n"
                "- `medio`: plausivel, mas nao esperado naquele momento especifico\n"
                "- `baixo`: pretexto generico ou incoerente com o cenario pedido\n"
                "Julgue com honestidade o que voce de fato escreveu -- nao repita "
                "mecanicamente o alvo do nivel '{difficulty}' se o texto que voce produziu "
                "não atingiu aquele alinhamento.\n\n"

                "## 3.7 FORMATO DE LINKS (links) -- ISSUE #5\n"
                "Cada item de `links` e um OBJETO com `text` (o texto exibido, o que a "
                "vitima le e clica) e `href` (o destino real do link). NUNCA uma string "
                "solta. Para simular a pista `link_text_mismatch`, faca o `text` sugerir "
                "um destino diferente do `href` real (ex.: text 'Acessar minha conta no "
                "banco oficial', href para um dominio com typosquatting) -- quando essa "
                "pista estiver na sua lista de `cues` para este item, o mesmo link deve "
                "estar refletido aqui com essa divergencia. Se o item nao tiver link (ver "
                "VARIEDADE ESTRUTURAL acima), `links` e uma lista vazia `[]`.\n\n"

                "## 4. EXEMPLOS DE REFERÊNCIA (FEW-SHOT LEARNING)\n"
                "Analise as táticas, métodos e gatilhos psicológicos descritos nos documentos de pesquisa para garantir consistência com padrões acadêmicos estabelecidos.\n\n"
                
                "## 5. CHAIN OF THOUGHT - RACIOCÍNIO ESTRUTURADO EM ETAPAS\n"
                "Siga este processo de raciocínio passo a passo:\n\n"
                
                "**ETAPA 1 - ANÁLISE:**\n"
                "- Qual é o cenário solicitado? Qual organização/situação está sendo simulada?\n"
                "- Quem seria o alvo típico? Quais elementos tornam este cenário plausível?\n\n"
                
                "**ETAPA 2 - SELEÇÃO DE TÁTICAS:**\n"
                "- Quais técnicas de phishing do conhecimento acadêmico são mais aplicáveis?\n"
                "- Gatilhos psicológicos relevantes: quais usar?\n"
                "- Vetores de ataque apropriados ao contexto\n\n"
                
                "**ETAPA 3 - CONSTRUÇÃO DO EMAIL:**\n"
                "Como o nível '{difficulty}' deve influenciar cada componente?\n"
                "- Remetente: Como deve parecer no nível {difficulty}?\n"
                "- Assunto: Que grau de sofisticação é esperado?\n"
                "- Corpo: Quão convincente e personalizado deve ser?\n"
                "- Links/URLs: Que nível de camuflagem é necessário?\n"
                "- Call-to-action: Quão direto ou sutil deve ser?\n\n"
                
                "**ETAPA 4 - VALIDAÇÃO:**\n"
                "Verifique a completude e consistência:\n"
                "- ✓ Remetente definido?\n"
                "- ✓ Assunto apropriado?\n"
                "- ✓ Corpo completo e convincente?\n"
                "- ✓ Call-to-action claro?\n"
                "- ✓ Técnicas acadêmicas implementadas?\n"
                "- ✓ Nível de dificuldade respeitado?\n"
                "- ✓ Coerência entre cenário + táticas + nível?\n"
                "- ✓ Ficha do item seguida (nome, quem assina, detalhe do pretexto, ação, tom, "
                "estrutura, abertura e pistas-alvo)?\n"
                "- ✓ `cues` lista exatamente as pistas realmente presentes, com evidência literal?\n"
                "- ✓ `premise_alignment` reflete o que você de fato escreveu, não só o alvo do nível?\n\n"

                "## FORMATO DE RESPOSTA\n"
                "Gere APENAS o objeto JSON com os campos solicitados (receptor, remetente, assunto, conteudo, explicacao, categoria, links, cues, premise_alignment).\n"
                "Não mostre explicitamente os passos de raciocínio, mas seu resultado deve demonstrar que você seguiu o processo Chain-of-Thought, implementando:\n"
                "- As características específicas do nível '{difficulty}'\n"
                "- As táticas acadêmicas do conhecimento técnico\n"
                "- O cenário solicitado de forma completa e precisa\n"
                "- Raciocínio coerente e fundamentado em cada elemento"
            )
        )
        
        # Prompt SEPARADO para item legitimo (issue #3) -- nao e o
        # prompt de phishing com uma flag. O objetivo muda de
        # "construir isca convincente" para "construir comunicacao
        # real plausivel", entao o raciocinio, os criterios de
        # validacao e o que conta como "bom resultado" sao outros.
        self.legitimate_prompt_template = PromptTemplate(
            input_variables=["context", "difficulty", "relevant_docs", "variacao", "data_atual"],
            template=(
                "## 1. INSTRUÇÃO DE SISTEMA\n"
                "Você é um especialista em comunicação corporativa e segurança da informação, "
                "encarregado de escrever uma comunicação LEGÍTIMA e REAL (não um golpe) para um "
                "instrumento de pesquisa sobre detecção de phishing. Este item é o lado "
                "'controle' do experimento: precisa ser indistinguível, em qualidade e forma, de "
                "uma comunicação genuína que a organização mandaria.\n\n"

                "## 2. CONTEXTO RECUPERADO\n"
                "**CONHECIMENTO ACADÊMICO DA BASE VETORIAL (sinais de PHISHING a EVITAR):**\n"
                "{relevant_docs}\n\n"
                "Use este material apenas como lista negativa: identifique as táticas descritas "
                "e garanta que NENHUMA delas apareça no item que você vai gerar.\n\n"

                "## 3. ESPECIFICAÇÃO DA TAREFA\n"
                "**Nível de Dificuldade:** {difficulty}\n"
                "**Cenário Específico:** {context}\n"
                "**Data de hoje:** {data_atual} -- qualquer prazo ou data que o item citar "
                "(ver PRAZO REAL E VERIFICÁVEL abaixo) é relativo a hoje, nunca uma data do "
                "passado.\n\n"

                "### FICHA DO ITEM (OBRIGATÓRIO -- sorteada pelo sistema para este item)\n"
                "Cada chamada sua é independente e não sabe o que as outras geraram; por isso "
                "o sistema sorteia, para cada item, os detalhes abaixo. Siga a ficha: ela fixa "
                "DETALHES dentro do cenário pedido, nunca troca o cenário, e nunca autoriza "
                "nada que as regras de legitimidade abaixo proíbem.\n"
                "{variacao}\n\n"
                "Nunca abra com fórmulas prontas como 'Esperamos que você esteja bem'. Nunca "
                "deixe marcadores de template no texto, como [Nome]: use o nome da ficha.\n\n"
                f"{_REGRAS_DE_FORMA}"

                "### O QUE TORNA O ITEM LEGÍTIMO (OBRIGATÓRIO)\n"
                "- Domínio do remetente coerente e plausível para a organização do cenário\n"
                "- NUNCA pede senha, código de verificação, dados de cartão ou qualquer credencial\n"
                "- Se houver uma ação a tomar, direciona a um canal PRÓPRIO e já conhecido "
                "('abra o aplicativo oficial', 'acesse o portal interno pelo link que você já usa'), "
                "nunca a um link novo e desconhecido\n"
                "- Oferece um canal alternativo verificável para dúvidas (ramal, telefone "
                "institucional, e-mail de suporte já conhecido)\n"
                "- Pode incluir um aviso de segurança real ('nós nunca pedimos sua senha por "
                "e-mail ou telefone')\n"
                "- Tom institucional, sem urgência artificial nem ameaça\n\n"

                "### VARIEDADE ESTRUTURAL (OBRIGATÓRIO -- validado empiricamente na issue #20)\n"
                "Uma checagem contra geração real mostrou dois problemas. Já corrigidos por "
                "instruções mais concretas:\n"
                "- Pedir 'metade com link, metade sem' de forma abstrata não funciona -- cada "
                "chamada sua é independente e não sabe o que outras chamadas geraram, "
                "então toda vez convergia para o mesmo lado. A presença de link agora segue a "
                "REGRA FIXA por nível descrita em CARACTERÍSTICAS DOS NÍVEIS DE DIFICULDADE "
                "abaixo -- não é mais uma escolha livre sua.\n"
                "- COMPRIMENTO também varia por nível: nem toda comunicação legítima é um "
                "parágrafo institucional longo -- em FÁCIL, prefira uma confirmação objetiva de "
                "poucas linhas; em MÉDIO/DIFÍCIL, um parágrafo institucional mais completo é "
                "esperado.\n"
                "- Em MÉDIO e DIFÍCIL, inclua um PRAZO REAL E VERIFICÁVEL por extenso (ex.: "
                "'sua fatura vence em 15/07', 'o acesso expira em 3 dias úteis') -- não evite "
                "palavras como 'prazo'/'vence'/'expira' só por soarem urgentes: o que torna o "
                "item confiável não é a ausência de prazo, é o prazo ser uma DATA/CONDIÇÃO "
                "verificável e razoável, em vez de uma pressão vaga e artificial.\n\n"

                "### CARACTERÍSTICAS DOS NÍVEIS DE DIFICULDADE (para o item legítimo)\n"
                "Aqui, dificuldade não é 'quão convincente é o golpe' -- é 'quão fácil é o "
                "participante desconfiar sem motivo real' (o risco de falso alarme que este "
                "item testa):\n\n"

                "**FÁCIL:** sinais de confiança óbvios e numerosos -- domínio claramente "
                "oficial, saudação personalizada, nenhuma urgência, aviso de segurança "
                "explícito. LINK OBRIGATÓRIO: inclua em `links` o link do portal/app oficial "
                "(regra fixa deste nível -- issue #20).\n\n"

                "**MÉDIO:** legítimo mas com algum elemento que poderia gerar dúvida à primeira "
                "vista, sem nunca cruzar para pedido de credencial ou link suspeito. SEM LINK "
                "OBRIGATÓRIO: `links` deve ser `[]` neste nível -- direcione por instrução "
                "textual ('abra o app que você já tem instalado') ou telefone/ramal (regra "
                "fixa -- issue #20). PRAZO OBRIGATÓRIO: cite no `conteudo`, em texto corrido, "
                "uma data ou condição verificável -- por exemplo 'sua fatura vence em 15/07' "
                "ou 'o acesso expira em 3 dias úteis' (regra fixa -- issue #20; NÃO omita o "
                "prazo só porque soa urgente, ele é o que torna este nível 'médio').\n\n"

                "**DIFÍCIL:** legítimo mas com elementos que SUPERFICIALMENTE lembram phishing "
                "(remetente de um setor incomum, assunto que soa urgente) -- o participante "
                "precisa checar os sinais de verdade (domínio, ausência de pedido de "
                "credencial, canal alternativo) para não cair em falso alarme. PRAZO "
                "OBRIGATÓRIO: cite no `conteudo` um prazo apertado mas REAL e verificável -- "
                "por exemplo 'o pagamento deve ser feito até amanhã, dia 12/07' (regra fixa -- "
                "issue #20). LINK OBRIGATÓRIO: inclua em `links` o link do canal oficial, mesmo "
                "com o elemento que gera dúvida (regra fixa deste nível -- issue #20).\n\n"

                "## 4. CHAIN OF THOUGHT\n"
                "**ETAPA 1 - ANÁLISE:** Qual comunicação real essa organização mandaria neste "
                "cenário? Que rotina ela reflete?\n"
                "**ETAPA 2 - SINAIS DE LEGITIMIDADE:** Quais dos sinais obrigatórios acima fazem "
                "sentido aqui? Qual canal alternativo é plausível?\n"
                "**ETAPA 3 - CONSTRUÇÃO:** Escreva o item aplicando o nível '{difficulty}' aos "
                "sinais de confiança (não a técnicas de engenharia social -- este item não usa "
                "nenhuma).\n"
                "**ETAPA 4 - VALIDAÇÃO:** Confirme que nada no texto pede credencial, nenhum "
                "link leva a domínio externo desconhecido, e não há tática de phishing da lista "
                "negativa presente.\n\n"

                "## TAXONOMIA DE PISTAS (cues) -- ISSUE #5\n"
                "Este item é LEGÍTIMO: o campo `cues` deve ser SEMPRE uma lista vazia `[]`. "
                "As pistas abaixo descrevem indicadores de PHISHING, e nenhuma delas pode "
                "estar presente aqui -- é exatamente isso que torna o item confiável:\n"
                f"{_TAXONOMIA_DE_PISTAS}\n\n"
                "Não preencha `premise_alignment`: o Phish Scale (issue #9) mede dificuldade "
                "de DETECTAR phishing, o que não se aplica a um item que não é phishing.\n\n"

                "## FORMATO DE LINKS (links) -- ISSUE #5\n"
                "Cada item de `links` é um OBJETO com `text` (texto exibido) e `href` "
                "(destino real). Aqui os dois devem ser COERENTES -- o texto do link "
                "descreve honestamente para onde ele leva (ex.: text 'Acessar o app "
                "oficial', href do próprio domínio da organização) -- link_text_mismatch é "
                "uma pista de phishing e não pode aparecer num item legítimo. Se não houver "
                "link, `links` é `[]`.\n\n"

                "## FORMATO DE RESPOSTA\n"
                "Gere APENAS o objeto JSON com os campos solicitados (receptor, remetente, "
                "assunto, conteudo, explicacao, categoria, links, cues).\n"
                "O campo `explicacao` deve explicar POR QUE o item é confiável, listando os "
                "sinais de legitimidade presentes -- NUNCA invente um defeito ou indicador de "
                "phishing que não existe só para preencher o campo. O campo `cues` deve vir "
                "vazio: `[]`."
            )
        )

        # Canais novos (issue #6): um LLM (`with_structured_output`
        # proprio) e dois prompts (malicioso/legitimo) por canal --
        # mesma separacao de chains com objetivos opostos que o email
        # ja usa (#3), so que schemas diferentes (WebsiteItemDraft,
        # PhoneCallItemDraft, PixQrItemDraft) em vez de reusar
        # GeneratedItemDraft, que fica intocado por esta issue.
        self.website_llm = _structured(WebsiteItemDraft, temperature, max_tokens_geracao)
        self.phone_call_llm = _structured(PhoneCallItemDraft, temperature, max_tokens_geracao)
        self.pix_qr_llm = _structured(PixQrItemDraft, temperature, max_tokens_geracao)
        # sms/whatsapp (issue #6, desbloqueados pela phishing-quest-api
        # #68): mesma separacao de LLM/prompt por canal dos 3 acima.
        self.sms_llm = _structured(SmsItemDraft, temperature, max_tokens_geracao)
        self.whatsapp_llm = _structured(WhatsAppItemDraft, temperature, max_tokens_geracao)

        _campos_canal = "content, explicacao, categoria"

        self.website_prompt_template = PromptTemplate(
            input_variables=["context", "difficulty", "relevant_docs"],
            template=_construir_prompt_canal(
                "Você é um especialista em cibersegurança criando um SITE FALSO "
                "(phishing via web) educacional, baseado em pesquisas acadêmicas.",
                _REGRAS_WEBSITE,
                "",
                _campos_canal,
            ),
        )
        self.website_legitimate_prompt_template = PromptTemplate(
            input_variables=["context", "difficulty", "relevant_docs"],
            template=_construir_prompt_canal(
                "Você é um especialista em comunicação institucional criando a página "
                "REAL e LEGÍTIMA (não um golpe) que uma organização manteria -- o lado "
                "'controle' do experimento.",
                _REGRAS_WEBSITE_LEGITIMO,
                "",
                _campos_canal,
            ),
        )
        self.phone_call_prompt_template = PromptTemplate(
            input_variables=["context", "difficulty", "relevant_docs"],
            template=_construir_prompt_canal(
                "Você é um especialista em cibersegurança criando o ROTEIRO de uma "
                "LIGAÇÃO de vishing (phishing por voz) educacional, baseado em "
                "pesquisas acadêmicas.",
                _REGRAS_PHONE_CALL,
                "",
                _campos_canal,
            ),
        )
        self.phone_call_legitimate_prompt_template = PromptTemplate(
            input_variables=["context", "difficulty", "relevant_docs"],
            template=_construir_prompt_canal(
                "Você é um especialista em atendimento institucional criando o "
                "ROTEIRO de uma ligação REAL e LEGÍTIMA (não um golpe) -- o lado "
                "'controle' do experimento.",
                _REGRAS_PHONE_CALL_LEGITIMO,
                "",
                _campos_canal,
            ),
        )
        self.pix_qr_prompt_template = PromptTemplate(
            input_variables=["context", "difficulty", "relevant_docs"],
            template=_construir_prompt_canal(
                "Você é um especialista em cibersegurança criando uma cobrança PIX/QR "
                "FALSA educacional, baseada em pesquisas acadêmicas.",
                _REGRAS_PIX_QR,
                "",
                _campos_canal,
            ),
        )
        self.pix_qr_legitimate_prompt_template = PromptTemplate(
            input_variables=["context", "difficulty", "relevant_docs"],
            template=_construir_prompt_canal(
                "Você é um especialista financeiro criando uma cobrança PIX REAL e "
                "LEGÍTIMA (não um golpe) -- o lado 'controle' do experimento.",
                _REGRAS_PIX_QR_LEGITIMO,
                "",
                _campos_canal,
            ),
        )
        self.sms_prompt_template = PromptTemplate(
            input_variables=["context", "difficulty", "relevant_docs"],
            template=_construir_prompt_canal(
                "Você é um especialista em cibersegurança criando um SMS de smishing "
                "(phishing por SMS) educacional, baseado em pesquisas acadêmicas.",
                _REGRAS_SMS,
                "",
                _campos_canal,
            ),
        )
        self.sms_legitimate_prompt_template = PromptTemplate(
            input_variables=["context", "difficulty", "relevant_docs"],
            template=_construir_prompt_canal(
                "Você é um especialista em comunicação institucional criando um SMS "
                "REAL e LEGÍTIMO (não um golpe) -- o lado 'controle' do experimento.",
                _REGRAS_SMS_LEGITIMO,
                "",
                _campos_canal,
            ),
        )
        self.whatsapp_prompt_template = PromptTemplate(
            input_variables=["context", "difficulty", "relevant_docs"],
            template=_construir_prompt_canal(
                "Você é um especialista em cibersegurança criando uma CONVERSA DE "
                "WHATSAPP de golpe educacional, baseada em pesquisas acadêmicas.",
                _REGRAS_WHATSAPP,
                "",
                _campos_canal,
            ),
        )
        self.whatsapp_legitimate_prompt_template = PromptTemplate(
            input_variables=["context", "difficulty", "relevant_docs"],
            template=_construir_prompt_canal(
                "Você é um especialista em atendimento institucional criando uma "
                "CONVERSA DE WHATSAPP REAL e LEGÍTIMA (não um golpe) -- o lado "
                "'controle' do experimento.",
                _REGRAS_WHATSAPP_LEGITIMO,
                "",
                _campos_canal,
            ),
        )

        self.hyde_prompt_template = PromptTemplate(
            input_variables=["query"],
            template=(
                "Como especialista em cibersegurança, gere uma resposta técnica e específica para a consulta do usuário. "
                "Esta resposta deve incluir terminologia precisa, conceitos técnicos e detalhes específicos que um documento acadêmico sobre o tópico conteria.\n\n"

                "**Consulta:** {query}\n\n"

                "**Resposta técnica (inclua métodos específicos, terminologia acadêmica e conceitos detalhados):**\n"
            )
        )

        # Anotador as cegas (piloto 2): recebe so o que o especialista
        # recebe (remetente, destinatario, assunto, corpo, links) e o
        # cenario -- nunca a ficha, o nivel pedido nem se o item e golpe.
        self.annotation_prompt_template = PromptTemplate(
            input_variables=["cenario", "remetente", "receptor", "assunto", "conteudo", "links"],
            template=(
                "## TAREFA\n"
                "Você é um anotador independente de pistas de phishing. Leia a mensagem "
                "abaixo e marque SOMENTE as pistas da taxonomia que estão de fato presentes "
                "no texto. Você não sabe como a mensagem foi produzida nem se ela é golpe "
                "ou comunicação legítima: julgue apenas o que está escrito. Uma lista vazia "
                "é uma resposta válida.\n\n"
                "## TAXONOMIA (definições operacionais)\n"
                f"{_TAXONOMIA_DE_PISTAS}\n\n"
                "## REGRAS\n"
                "- Para cada pista: `code`, `campo` (onde ela está: `remetente`, `assunto` "
                "ou `conteudo`) e `evidencia`, o trecho copiado literalmente desse campo, "
                "sem aspas.\n"
                "- Marque cada pista uma vez, com o trecho mais claro.\n"
                "- `sender_domain_mismatch` e `typosquat` exigem um domínio na evidência "
                "(o do endereço do remetente ou o destino de um link). Nome de pessoa, de "
                "setor ou de organização não é domínio.\n"
                "- `sender_domain_mismatch` só quando o domínio do endereço não é o da "
                "organização que a mensagem diz representar. Domínio coerente com a "
                "organização não é pista.\n"
                "- `typosquat` só quando o domínio imita o oficial com caractere trocado, a "
                "mais ou a menos.\n"
                "- `urgency` é tempo (prazo, 'imediatamente', consequência iminente); "
                "`scarcity` é quantidade ou oferta limitada. Prazo para cumprir uma "
                "obrigação é `urgency`.\n"
                "- `generic_greeting` só quando a saudação não usa o nome do destinatário.\n"
                "- `link_text_mismatch`: compare o texto exibido de cada link com o "
                "destino real, na lista de links.\n\n"
                "## PREMISSA (premise_alignment)\n"
                "Julgue também o quanto o PRETEXTO da mensagem se encaixa na rotina de "
                "quem recebe, dado o cenário: {cenario}\n"
                "- `alto`: o pretexto faz parte da rotina de quem recebe\n"
                "- `medio`: plausível, mas não esperado naquele momento\n"
                "- `baixo`: pretexto genérico ou incoerente com o cenário\n\n"
                "## MENSAGEM\n"
                "Remetente: {remetente}\n"
                "Destinatário: {receptor}\n"
                "Assunto: {assunto}\n"
                "Corpo:\n{conteudo}\n\n"
                "Links (texto exibido e destino real):\n{links}\n"
            ),
        )
        self.annotation_chain = self.annotation_prompt_template | self.annotation_llm

        self.chain = self.prompt_template | self.llm
        self.legitimate_chain = self.legitimate_prompt_template | self.llm
        self.hyde_chain = self.hyde_prompt_template | self.text_llm

        self.website_chain = self.website_prompt_template | self.website_llm
        self.website_legitimate_chain = (
            self.website_legitimate_prompt_template | self.website_llm
        )
        self.phone_call_chain = self.phone_call_prompt_template | self.phone_call_llm
        self.phone_call_legitimate_chain = (
            self.phone_call_legitimate_prompt_template | self.phone_call_llm
        )
        self.pix_qr_chain = self.pix_qr_prompt_template | self.pix_qr_llm
        self.pix_qr_legitimate_chain = (
            self.pix_qr_legitimate_prompt_template | self.pix_qr_llm
        )
        self.sms_chain = self.sms_prompt_template | self.sms_llm
        self.sms_legitimate_chain = self.sms_legitimate_prompt_template | self.sms_llm
        self.whatsapp_chain = self.whatsapp_prompt_template | self.whatsapp_llm
        self.whatsapp_legitimate_chain = (
            self.whatsapp_legitimate_prompt_template | self.whatsapp_llm
        )

        # Dispatch por canal usado por generate_channel_item -- indexado
        # por (channel.value, is_malicious), unica fonte de verdade de
        # "qual chain atende qual canal", em vez de um if/elif longo.
        self._chains_por_canal = {
            ("website", True): self.website_chain,
            ("website", False): self.website_legitimate_chain,
            ("phone_call", True): self.phone_call_chain,
            ("phone_call", False): self.phone_call_legitimate_chain,
            ("pix_qr", True): self.pix_qr_chain,
            ("pix_qr", False): self.pix_qr_legitimate_chain,
            ("sms", True): self.sms_chain,
            ("sms", False): self.sms_legitimate_chain,
            ("whatsapp", True): self.whatsapp_chain,
            ("whatsapp", False): self.whatsapp_legitimate_chain,
        }

    async def generate_response(
        self,
        difficulty: str,
        context: str,
        relevant_docs,
        is_malicious: bool = True,
        variacao: Optional[VariationSpec] = None,
        sortear_variacao: Optional[Callable[[], VariationSpec]] = None,
    ) -> ValidatedItemDraft:
        """
        Gera um item (phishing ou legítimo) baseado no contexto, dificuldade e documentos relevantes.

        Args:
            difficulty: Nível de dificuldade, já validado e normalizado
                pelo chamador -- um dos três valores canônicos
                ('facil', 'medio', 'dificil'; ver
                app.domain.models.difficulty.Difficulty). Esta função
                não valida nem normaliza mais: antes, um valor fora do
                vocabulário caía num fallback silencioso para 'médio',
                o que escondia o contrato quebrado corrigido na issue
                #2 em vez de expor o problema.
            context: Contexto específico do cenário
            relevant_docs: Documentos acadêmicos relevantes
            is_malicious: True gera phishing (comportamento histórico,
                default para não quebrar chamador antigo); False gera
                item legítimo -- issue #3. NÃO é uma flag no mesmo
                prompt: são duas chains com objetivos opostos ("montar
                isca convincente" vs. "montar comunicação real
                plausível"), como o item legítimo deixa explícito.
            variacao: ficha sorteada para este item (ver
                VariationSpec e VariationSampler). Entra no prompt como
                `{variacao}` e alimenta as validacoes (nome do
                destinatario, pistas-alvo). None so para chamador que
                nao sorteia ficha -- o prompt entao pede escolha livre.
            sortear_variacao: quando o item volta estruturalmente
                invalido e e gerado de novo, cada nova tentativa usa a
                ficha devolvida por esta funcao (piloto 2: o item com
                "[Nome da Universidade]" repetiu o marcador nas 2
                regeneracoes com a mesma ficha). Sem ela, repete a ficha.

        Returns:
            ValidatedItemDraft: NÃO inclui `nivel` nem `is_malicious`
            (ver issue #11 -- ambos são entrada da geração, não saída
            do LLM). `cues` e `premise_alignment` vêm do anotador às
            cegas quando ele está ligado (piloto 2), senão do próprio
            gerador; em ambos os casos validados por `_validar_cues`
            (spans calculados no campo certo, pistas sem lastro
            removidas, item legítimo sem pista). `phish_scale` (issue
            #9) é montado a partir deles -- None para item legítimo.
            `target_cues`/`variation_spec` são os da ficha de fato usada,
            e `validacao` traz o relatório do que foi corrigido.

        Raises:
            ItemInvalidoError: o item continuou com marcador de template
                ou com remetente ou destinatário sem endereço de e-mail,
                instituição real, domínio caricato ou "Ação Necessária" no
                assunto depois de
                MAX_REGENERACOES_POR_MARCADOR novas gerações.
        """
        chain = self.chain if is_malicious else self.legitimate_chain
        relatorio = RelatorioValidacao()
        ficha = variacao

        for tentativa in range(MAX_REGENERACOES_POR_MARCADOR + 1):
            if tentativa > 0 and sortear_variacao is not None:
                ficha = sortear_variacao()
            entrada = {
                "context": context,
                "difficulty": difficulty,
                "relevant_docs": relevant_docs,
                "variacao": renderizar_ficha(ficha),
                "data_atual": _data_atual_por_extenso(),
            }
            try:
                draft = await chain.ainvoke(entrada)
            except Exception as e:
                logging.error(f"Error generating response: {e}")
                raise e

            problema = self._problema_estrutural(draft)
            if problema is None:
                break
            motivo, detalhe = problema
            logging.warning(
                "Item gerado invalido (%s: %s, tentativa %d) -- gerando de novo.",
                motivo,
                detalhe,
                tentativa + 1,
            )
            if tentativa == MAX_REGENERACOES_POR_MARCADOR:
                raise ItemInvalidoError(
                    f"item continuou invalido ({motivo}: {detalhe}) apos "
                    f"{MAX_REGENERACOES_POR_MARCADOR} regeneracoes"
                )
            contador = _CONTADOR_POR_MOTIVO[motivo]
            setattr(relatorio, contador, getattr(relatorio, contador) + 1)

        # Antes da anotacao as cegas e dos spans: os dois precisam ver o
        # texto final, e um link Markdown convertido entra em `links`.
        (
            draft.conteudo,
            draft.links,
            relatorio.links_markdown_convertidos,
            relatorio.negritos_markdown_removidos,
        ) = converter_markdown(draft.conteudo, draft.links)
        draft.conteudo, relatorio.assunto_removido_do_corpo = remover_assunto_repetido(
            draft.assunto, draft.conteudo
        )

        cues, premise_alignment = draft.cues, draft.premise_alignment
        if is_malicious and self.anotacao_cega:
            relatorio.anotacao_cega = True
            relatorio.cues_autodeclaradas = [c.code for c in draft.cues]
            relatorio.premise_alignment_autodeclarado = (
                draft.premise_alignment.value if draft.premise_alignment else None
            )
            anotacao = await self._anotar_as_cegas(draft, context)
            cues = [
                Cue(code=p.code, evidencia=p.evidencia, campo=p.campo) for p in anotacao.pistas
            ]
            premise_alignment = anotacao.premise_alignment

        if is_malicious:
            cues = self._completar_pistas_de_dominio_por_construcao(cues, ficha, draft, relatorio)

        draft.cues = self._validar_cues(
            draft.conteudo,
            cues,
            is_malicious,
            nome_destinatario=ficha.nome_destinatario if ficha else None,
            relatorio=relatorio,
            campos={
                "conteudo": draft.conteudo,
                "assunto": draft.assunto,
                "remetente": draft.remetente,
            },
        )
        draft.premise_alignment = premise_alignment
        if is_malicious and ficha is not None:
            registrar_aderencia(draft.cues, ficha.pistas_alvo, relatorio)
        draft.phish_scale = self._compute_phish_scale(draft.cues, draft.premise_alignment, is_malicious)
        return ValidatedItemDraft(
            **{
                **draft.model_dump(),
                "validacao": relatorio.model_dump(mode="json"),
                "target_cues": list(ficha.pistas_alvo) if (ficha and is_malicious) else None,
                "variation_spec": ficha.model_dump(mode="json") if ficha else None,
            }
        )

    def _problema_estrutural(self, draft: GeneratedItemDraft):
        """(motivo, detalhe) quando o item nao pode ser usado como veio,
        ou None. Marcador de template (piloto 1 e 2), remetente sem
        endereco de e-mail (piloto 2), destinatario sem e-mail e dominio
        caricato (piloto 3), instituicao real ou "Acao Necessaria" no
        assunto (teste da versao do piloto 3). Vale para phishing e
        legitimo: senao a regra vira atalho para o rotulo.
        """
        textos_de_link = [link.text for link in draft.links]
        # O endereco do destinatario so e checado quanto a colchetes:
        # "aluno@example.com" ali e comum e nao e o que o especialista
        # analisa (remetente, assunto e corpo).
        marcadores = encontrar_marcadores(
            draft.remetente, draft.assunto, draft.conteudo, textos_de_link=textos_de_link
        ) + encontrar_marcadores(
            draft.receptor, textos_de_link=textos_de_link, nomes_genericos=False
        )
        if marcadores:
            return "marcador", marcadores
        if endereco_de_email(draft.remetente) is None:
            return "remetente_sem_email", draft.remetente
        if endereco_de_email(draft.receptor) is None:
            return "destinatario_sem_email", draft.receptor
        # Instituicao real: bloqueio so em PERSONIFICACAO, nao em
        # qualquer mencao (piloto 5, item 15 do cabecalho de
        # item_validation.py). "Entregue pelos Correios" no corpo, num
        # cenario de logistica, e mencao legitima; "@correios-br.com" no
        # remetente, ou o dominio real em qualquer campo, e
        # personificacao. Nome/sigla so contam em remetente/destinatario/
        # links; dominio real conta em qualquer campo (nao ha "mencao
        # inocente" de um dominio -- escreve-lo e a propria forma de
        # apontar para o endereco dele).
        instituicoes = encontrar_dominios_reais(
            draft.remetente,
            draft.receptor,
            draft.assunto,
            draft.conteudo,
            *(link.text for link in draft.links),
            *(link.href for link in draft.links),
        ) + encontrar_nomes_de_instituicoes_reais(
            draft.remetente,
            draft.receptor,
            *(link.text for link in draft.links),
            *(link.href for link in draft.links),
        )
        if instituicoes:
            return "instituicao_real", instituicoes
        caricatos = encontrar_dominios_caricatos(
            draft.remetente,
            draft.receptor,
            draft.conteudo,
            *(link.href for link in draft.links),
        )
        if caricatos:
            return "dominio_caricato", caricatos
        formula = formula_proibida_no_assunto(draft.assunto)
        if formula:
            return "assunto_proibido", formula
        return None

    async def _anotar_as_cegas(self, draft: GeneratedItemDraft, cenario: str) -> AnotacaoCega:
        """2a chamada: anota pistas e premissa a partir do item pronto,
        sem a ficha, o nivel pedido nem a informacao de que e golpe --
        a mesma situacao do especialista (ver ConteudoParaAvaliar).
        Erro aqui propaga como falha de geracao do item.
        """
        try:
            return await self.annotation_chain.ainvoke(
                {
                    "cenario": cenario,
                    "remetente": draft.remetente,
                    "receptor": draft.receptor,
                    "assunto": draft.assunto,
                    "conteudo": draft.conteudo,
                    "links": _links_para_anotador(draft.links),
                }
            )
        except Exception as e:
            logging.error(f"Error annotating item: {e}")
            raise e

    def _completar_pistas_de_dominio_por_construcao(
        self,
        cues: List[Cue],
        ficha: Optional[VariationSpec],
        draft: GeneratedItemDraft,
        relatorio: RelatorioValidacao,
    ) -> List[Cue]:
        """Pistas de dominio (typosquat, sender_domain_mismatch) sao
        DETERMINISTICAS por construcao: o codigo decide o dominio exato
        e onde ele entra (`ficha.dominio_da_pista`/`dominio_da_pista_em`
        -- ver VariationSampler._endereco_e_dominio_da_pista). O LLM
        quase nunca as autoanota: a secao 3.5 do prompt (e o anotador as
        cegas) pedem evidencia como trecho de remetente/assunto/
        conteudo, mas o artefato dessas pistas fica no remetente ou num
        link, raramente citado de volta no corpo -- no piloto 5, 0 de 8
        typosquats-alvo e 0 de 6 sender_domain_mismatch-alvo no dificil
        sairam anotados.

        Como o artefato e conhecido, a pista entra aqui por construcao
        quando falta -- evidencia e o proprio endereco/dominio ofensor,
        nunca um trecho do corpo. So insere quando o dominio de fato
        aparece no item gerado (remetente ou algum link): o LLM pode
        ter ignorado a ficha, e nesse caso nao ha o que completar (a
        pista realmente nao esta no e-mail).

        Depende do sorteio nunca colocar as duas pistas de dominio
        juntas no alvo de um item (ver VariationSampler
        ._pares_sem_redundancia_de_dominio): so ha um
        `dominio_da_pista` por ficha, entao no maximo uma pista falta.
        A checagem abaixo torna essa dependencia explicita -- se um
        pool voltar a permitir as duas juntas sem atualizar esta
        funcao, falha alto em vez de atribuir o mesmo dominio as duas
        pistas por engano.
        """
        if ficha is None or not ficha.dominio_da_pista:
            return cues
        ja_anotadas = {c.code for c in cues}
        faltando = [
            p for p in PISTAS_DE_DOMINIO if p in ficha.pistas_alvo and p not in ja_anotadas
        ]
        if not faltando:
            return cues
        if len(faltando) > 1:
            raise ValueError(
                f"mais de uma pista de dominio faltando ({[p.value for p in faltando]}) para "
                "um unico dominio_da_pista -- ver VariationSampler"
                "._pares_sem_redundancia_de_dominio"
            )

        dominio = ficha.dominio_da_pista
        if dominio in (draft.remetente or ""):
            campo = "remetente"
        elif any(dominio in (link.href or "") for link in draft.links):
            # href nao e um CampoDaPista valido (so remetente/assunto/
            # conteudo) -- calcular_spans tenta localizar mesmo assim e
            # mantem a pista sem span quando nao acha, o mesmo
            # tratamento que ja existe para evidencia nao literal.
            campo = None
        else:
            return cues

        relatorio.cues_completadas_por_construcao = list(faltando)
        return cues + [Cue(code=p, evidencia=dominio, campo=campo) for p in faltando]

    def _validar_cues(
        self,
        conteudo: str,
        cues: List[Cue],
        is_malicious: bool,
        nome_destinatario: Optional[str] = None,
        relatorio: Optional[RelatorioValidacao] = None,
        campos: Optional[Dict[str, Optional[str]]] = None,
    ) -> List[Cue]:
        """Aplica os passos 5 e 9 da issue #5 depois da geracao, mais as
        validacoes dos lotes-piloto de 26 e 27/10/2026.

        Passo 9: item legitimo nunca deve ter pista de golpe. O prompt
        legitimo ja instrui `cues: []`, mas isso e disciplina de
        prompt, nao garantia -- aqui e onde a garantia de fato existe.
        Um LLM que "esquecer" a instrucao e descartado (com log e
        registro no relatorio), nao propagado: nao ha ganho em falhar a
        geracao inteira por causa de uma lista que deveria estar vazia.

        Passo 5, refeito nos pilotos: as posicoes sao CALCULADAS a partir
        da `evidencia`, no campo em que ela esta (remetente, assunto ou
        conteudo -- ver item_validation.calcular_spans). Span nulo
        significa uma coisa so: a evidencia nao e trecho literal do item.
        A pista continua MANTIDA nesse caso: o codigo pode estar certo
        mesmo quando a citacao nao esta.

        Removidas, com registro: `generic_greeting` com o nome do
        destinatario da ficha na saudacao, e pistas de dominio cuja
        evidencia nao tem dominio.
        """
        if not is_malicious:
            if cues:
                logging.warning(
                    "LLM emitiu %d pista(s) de phishing num item legitimo -- "
                    "descartando (issue #5, passo 9).",
                    len(cues),
                )
                if relatorio is not None:
                    relatorio.pistas_removidas.extend(
                        PistaRemovida(code=c.code, evidencia=c.evidencia, motivo="item_legitimo")
                        for c in cues
                    )
            return []

        validadas = calcular_spans(campos or {"conteudo": conteudo}, cues, relatorio)
        removidas_antes = len(relatorio.pistas_removidas) if relatorio else 0
        validadas = remover_saudacao_generica_falsa(
            conteudo, validadas, nome_destinatario, relatorio
        )
        validadas = remover_pistas_de_dominio_sem_dominio(validadas, relatorio)
        if relatorio is not None and len(relatorio.pistas_removidas) > removidas_antes:
            logging.warning(
                "Pistas removidas na validacao: %s",
                [r.motivo for r in relatorio.pistas_removidas[removidas_antes:]],
            )
        return validadas

    def _compute_phish_scale(
        self,
        cues: List[Cue],
        premise_alignment: Optional[PremiseAlignment],
        is_malicious: bool,
    ) -> Optional[PhishScale]:
        """Monta o Phish Scale (issue #9) DEPOIS da geracao e da
        validacao de cues -- nunca antes, e nunca a partir do que o
        LLM eventualmente tenha proposto para os campos derivados.

        None para item legitimo ou quando o LLM nao julgou
        `premise_alignment` (prompt legitimo nao pede o campo, ver
        `legitimate_prompt_template`): "dificuldade de detectar
        phishing" nao se aplica a um item que nao e phishing.

        `cue_count` e SEMPRE `len(cues)` deste mesmo draft (ja
        validado por `_validar_cues`) -- nunca um numero que o LLM
        declara a parte, exatamente o que a issue pede ("nao de campo
        livre... duas fontes de verdade para a mesma contagem vao
        divergir").
        """
        if not is_malicious or premise_alignment is None:
            return None

        cue_count = len(cues)
        return PhishScale(
            cue_count=cue_count,
            premise_alignment=premise_alignment,
            difficulty_estimated=self._derivar_dificuldade_estimada(
                cue_count, premise_alignment
            ),
        )

    def _derivar_dificuldade_estimada(
        self, cue_count: int, premise_alignment: PremiseAlignment
    ) -> Difficulty:
        """Regra de derivacao DETERMINISTICA e documentada da issue #9
        (passo 4) -- nunca um terceiro palpite do modelo.

        Pontuacao por eixo, somada:

        - `cue_count`: 0-1 pistas -> 2 pontos (poucas pistas, mais
          dificil de perceber); 2 pistas -> 1 ponto; 3+ pistas -> 0
          pontos (muitas pistas, mais facil de perceber).
        - `premise_alignment`: `alto` -> 2 pontos; `medio` -> 1 ponto;
          `baixo` -> 0 pontos.

        Soma 0-1 -> facil; 2-3 -> medio; 4 -> dificil. Bate com o
        esboco da issue: "muitas pistas + baixo/medio -> facil" da
        soma 0 ou 1; "poucas pistas + alto" da soma 4 -> dificil; as
        combinacoes intermediarias caem em medio. Os pontos de corte
        sao candidatos a revisao quando houver dado empirico de
        calibracao (ver `phishing-quest-api` #66) -- por isso isolados
        nesta funcao, e nao espalhados pelo prompt.
        """
        if cue_count <= 1:
            pontos_cue = 2
        elif cue_count == 2:
            pontos_cue = 1
        else:
            pontos_cue = 0

        pontos_alinhamento = {
            PremiseAlignment.ALTO: 2,
            PremiseAlignment.MEDIO: 1,
            PremiseAlignment.BAIXO: 0,
        }[premise_alignment]

        soma = pontos_cue + pontos_alinhamento
        if soma <= 1:
            return Difficulty.FACIL
        if soma <= 3:
            return Difficulty.MEDIO
        return Difficulty.DIFICIL

    async def generate_channel_item(
        self, channel: str, difficulty: str, context: str, relevant_docs, is_malicious: bool = True
    ) -> dict:
        """Gera um item de um canal NOVO (issue #6: website, phone_call,
        pix_qr, sms ou whatsapp -- os dois ultimos desbloqueados pela
        phishing-quest-api #68, ver app.domain.models.channel.Channel).

        Espelha `generate_response` (email) na forma -- mesmos
        parametros, mesma selecao malicioso/legitimo por chain
        separada -- mas devolve um dict solto (`content_json`,
        `explicacao`, `categoria`), nao um `GeneratedItemDraft`: os
        canais novos nao tem `cues`/`phish_scale` (fora do escopo desta
        entrega, ver comentario da issue #6), entao nao ha um schema
        de retorno unico que fizesse sentido para os dois mundos sem
        forcar campos vazios artificiais.

        Args:
            channel: um dos `GENERATION_SUPORTADOS` nao-email, como
                string (`.value` do enum `Channel`). Chamador (o
                endpoint) e quem valida que o canal e suportado --
                esta funcao apenas espelha o dispatch.
        """
        chain = self._chains_por_canal.get((channel, is_malicious))
        if chain is None:
            raise ValueError(f"Canal '{channel}' nao tem chain de geracao configurada.")

        try:
            draft = await chain.ainvoke(
                {"context": context, "difficulty": difficulty, "relevant_docs": relevant_docs}
            )
        except Exception as e:
            logging.error(f"Error generating channel item ({channel}): {e}")
            raise e

        return {
            "content_json": draft.content.model_dump(),
            "explicacao": draft.explicacao,
            "categoria": draft.categoria,
        }

    async def generate_hypothetical_answer(self, query: str) -> str:
        """
        Gera uma resposta hipotética para melhorar a busca semântica (HyDE).
        
        Args:
            query: Consulta do usuário
            
        Returns:
            str: Resposta hipotética rica em contexto técnico
        """
        try:
            response = await self.hyde_chain.ainvoke({"query": query})
            return _texto_da_resposta(response).strip().strip('"')
        except Exception as e:
            logging.error(f"Error generating hypothetical answer: {e}")
            return query


    async def fuse_and_summarize_context(self, generation_context: str, contexts: list[str]) -> str:
        """
        Funde múltiplos contextos em um resumo coeso e relevante.
        
        Args:
            generation_context: Contexto da tarefa de geração
            contexts: Lista de contextos a serem fundidos
            
        Returns:
            str: Contexto fundido e resumido
        """
        if not contexts:
            return "Conhecimento técnico específico não disponível."

        full_context_text = "\n\n---\n\n".join(contexts)

        prompt = PromptTemplate(
            input_variables=["generation_context", "full_context_text"],
            template=(
                "Analise os documentos acadêmicos e extraia o CONHECIMENTO TÉCNICO sobre phishing "
                "útil para o cenário abaixo. Você NÃO escreve o e-mail: outra etapa o escreve, e "
                "este resumo vai igual para todos os itens de um lote.\n\n"

                "**CENÁRIO (só para decidir o que é relevante):**\n"
                "{generation_context}\n\n"

                "**DOCUMENTOS ACADÊMICOS:**\n"
                "{full_context_text}\n\n"

                "**INSTRUÇÕES DE EXTRAÇÃO:**\n"
                "1. Táticas, técnicas e métodos de phishing relevantes para o cenário\n"
                "2. Gatilhos psicológicos e estratégias de engenharia social descritos nos "
                "documentos\n"
                "3. Terminologia técnica e como cada técnica aparece num e-mail, descrita (não "
                "escrita como texto pronto)\n"
                "4. Relação das técnicas com níveis de sofisticação (fácil, médio, difícil)\n\n"

                "**PROIBIDO NA SAÍDA:** escrever um e-mail ou um modelo de e-mail (assunto, "
                "saudação, corpo, assinatura); nomes de instituições, empresas ou pessoas citadas "
                "nos documentos; texto entre colchetes. Use tópicos curtos.\n\n"

                "**CONHECIMENTO TÉCNICO (em português brasileiro, em tópicos):**"
            )
        )
        
        fusion_chain = prompt | self.text_llm
        
        try:
            response = await fusion_chain.ainvoke({
                "generation_context": generation_context,
                "full_context_text": full_context_text
            })
            fundido = _texto_da_resposta(response).strip()
        except Exception as e:
            logging.error(f"Error fusing context: {e}")
            fundido = full_context_text
        # Lote local de 27/10: a fusao devolveu um e-mail pronto assinado
        # "Universidade Federal do Rio de Janeiro" com "[Seu Nome]", e o
        # gerador copiou a instituicao em todas as regeneracoes.
        limpo, removidos = limpar_contexto_fundido(fundido)
        if removidos:
            logging.warning(
                "Contexto fundido com instituicao real ou marcador; removido: %s", removidos
            )
        return limpo


    async def translate_to_english_with_enrichment(self, text: str, difficulty: str) -> str:
        """
        Traduz e enriquece o texto com terminologia técnica explícita.
        """
        if not text or len(text.split()) < 5:
            return text

        prompt = PromptTemplate(
            input_variables=["text_to_translate", "difficulty"],
            template=(
                "Translate the following phishing email from Portuguese to English. "
                "Additionally, ENRICH the translation by explicitly mentioning the social engineering techniques used.\n\n"
                
                "**Instructions:**\n"
                "1. Translate all content accurately\n"
                "2. After the 'Implemented Techniques' section, ADD a paragraph explicitly stating:\n"
                "   - Which social engineering tactics are used (e.g., authority, urgency, personalization)\n"
                "   - How the email demonstrates sophisticated phishing techniques\n"
                "   - The {difficulty}-level characteristics present in the email\n\n"
                
                "**Text to translate:**\n"
                "{text_to_translate}\n\n"
                
                "**Enriched English translation:**"
            )
        )
        
        translation_chain = prompt | self.text_llm
        
        try:
            response = await translation_chain.ainvoke({
                "text_to_translate": text,
                "difficulty": difficulty
            })
            return _texto_da_resposta(response).strip()
        except Exception as e:
            logging.error(f"Error translating to English: {e}")
            return text