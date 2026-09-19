# app/domain/services/response_generator.py

import logging
from typing import List, Optional

from langchain_core.prompts import PromptTemplate
from app.domain.models.channel_item_draft import (
    PhoneCallItemDraft,
    PixQrItemDraft,
    SmsItemDraft,
    WebsiteItemDraft,
    WhatsAppItemDraft,
)
from app.domain.models.cue import Cue
from app.domain.models.difficulty import Difficulty
from app.domain.models.generated_item_draft import GeneratedItemDraft
from app.domain.models.phish_scale import PhishScale, PremiseAlignment
from langchain_openai import ChatOpenAI

# Descricao curta de cada codigo, injetada nos dois prompts (issue #5,
# passo 3): sem isso, o `Enum` do structured output so impede o modelo
# de INVENTAR um codigo fora da taxonomia -- nao ajuda o modelo a
# ESCOLHER o codigo certo para o que ele mesmo esta escrevendo.
_TAXONOMIA_DE_PISTAS = (
    "- sender_domain_mismatch: dominio do remetente nao corresponde a organizacao\n"
    "- typosquat: dominio com erro de digitacao proposital (ex.: empres4.net)\n"
    "- homoglyph: caractere visualmente parecido usado para enganar\n"
    "- urgency: apelo a urgencia ou prazo curto\n"
    "- authority: apelo a autoridade (banco, governo, chefia)\n"
    "- generic_greeting: saudacao generica, sem personalizacao\n"
    "- credential_request: solicitacao direta de senha ou dado sensivel\n"
    "- link_text_mismatch: texto do link diferente do destino real\n"
    "- unexpected_attachment: anexo inesperado ou fora do contexto\n"
    "- scarcity: apelo a escassez ou oferta por tempo limitado"
)


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
    def __init__(self, api_key: str, model_name: str = "gpt-4o-mini"):
        self.llm = ChatOpenAI(
            model_name=model_name,
            api_key=api_key,
            temperature=0.7
        ).with_structured_output(GeneratedItemDraft)

        self.text_llm = ChatOpenAI(
            model_name=model_name,
            api_key=api_key,
            temperature=0.2
        )

        self.prompt_template = PromptTemplate(
            input_variables=["context", "difficulty", "relevant_docs"],
            template=(
                "## 1. INSTRUÇÃO DE SISTEMA\n"
                "Você é um especialista em cibersegurança especializado na criação de emails de phishing educacionais baseados em pesquisas acadêmicas.\n\n"
                
                "## 2. CONTEXTO RECUPERADO\n"
                "**CONHECIMENTO ACADÊMICO DA BASE VETORIAL:**\n"
                "{relevant_docs}\n\n"
                
                "## 3. ESPECIFICAÇÃO DA TAREFA\n"
                "**Nível de Dificuldade:** {difficulty}\n"
                "**Cenário Específico:** {context}\n\n"

                "### VARIEDADE ESTRUTURAL (OBRIGATÓRIO)\n"
                "Nem todo phishing tem link: peça de dados por resposta direta, por anexo, "
                "ou peça uma ligação para um número informado no próprio email, variando entre "
                "os itens gerados. Um golpe que sempre depende de clicar em um link é menos "
                "realista e, em um corpus de pesquisa, cria um atalho estrutural (presença de "
                "link prevendo o rótulo) que permite ao participante acertar sem ler o "
                "conteúdo -- isso invalida a medição.\n\n"

                "### CARACTERÍSTICAS DOS NÍVEIS DE DIFICULDADE\n\n"
                
                "**FÁCIL:**\n"
                "- Remetente claramente suspeito ou genérico (ex: noreply@empresa123.com)\n"
                "- Assunto com erros ortográficos ou gramaticais evidentes\n"
                "- Urgência exagerada e óbvia ('URGENTE!!!', 'AÇÃO IMEDIATA')\n"
                "- Links visivelmente suspeitos ou encurtados\n"
                "- Formatação inconsistente ou amadora\n"
                "- Ausência de personalização (tratamento genérico)\n"
                "- Ameaças diretas e explícitas\n"
                "- Solicitação óbvia de informações sensíveis\n"
                "- Phish Scale: mire em 3 OU MAIS pistas da taxonomia abaixo, óbvias, e "
                "premissa `baixo` ou `medio` (pretexto genérico, sem relação com a rotina "
                "específica de quem recebe)\n\n"

                "**MÉDIO:**\n"
                "- Remetente parcialmente convincente mas com pequenas inconsistências\n"
                "- Assunto plausível mas com alguns indicadores de suspeita\n"
                "- Urgência moderada com justificativa aparente\n"
                "- Links que parecem legítimos à primeira vista\n"
                "- Formatação mais profissional, similar a comunicações empresariais\n"
                "- Personalização básica (nome do destinatário)\n"
                "- Mistura de informações verdadeiras com falsas\n"
                "- Uso de logos e identidade visual parcialmente convincentes\n"
                "- Solicitação indireta de ação (download, clique, verificação)\n"
                "- Phish Scale: mire em EXATAMENTE 2 pistas moderadas e premissa `medio`\n\n"

                "**DIFÍCIL:**\n"
                "- Remetente altamente convincente, indistinguível de comunicações legítimas\n"
                "- Assunto contextualmente perfeito e relevante\n"
                "- Urgência sutil e bem justificada (contexto empresarial realista)\n"
                "- Links com domínios similares aos originais (typosquatting sutil)\n"
                "- Formatação profissional idêntica às comunicações oficiais\n"
                "- Personalização avançada (cargo, projetos específicos, colegas)\n"
                "- Informações específicas e verificáveis sobre a empresa/pessoa\n"
                "- Identidade visual perfeita (logos, assinaturas, layout)\n"
                "- Contexto temporal relevante (eventos atuais, datas importantes)\n"
                "- Engenharia social sofisticada (psicologia, autoridade, reciprocidade)\n"
                "- Phish Scale: mire em 0 OU 1 pista, bem sutil, e premissa `alto` -- o "
                "pretexto precisa parecer parte genuína da rotina de quem recebe, dado o "
                "cenário '{context}'\n\n"

                "## 3.5 TAXONOMIA DE PISTAS (cues) -- ISSUE #5\n"
                "Alem do texto, anote em `cues` QUAIS das pistas abaixo estao de fato "
                "presentes no email que voce esta escrevendo. Use SOMENTE estes 10 codigos "
                "(nunca invente um novo):\n"
                f"{_TAXONOMIA_DE_PISTAS}\n\n"
                "Para cada pista, informe `evidencia`: o TRECHO LITERAL do `conteudo` que "
                "comprova a pista (copie exatamente, nao parafraseie -- isso sera conferido). "
                "Quando conseguir localizar esse trecho com precisao, informe tambem "
                "`span_start`/`span_end` (posicao inicial/final do trecho dentro de "
                "`conteudo`); se nao tiver certeza da posicao exata, deixe os dois como "
                "null -- e melhor omitir a posicao do que informar uma errada. So anote "
                "pistas REALMENTE presentes: uma lista vazia e melhor que uma pista forcada. "
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
            input_variables=["context", "difficulty", "relevant_docs"],
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
                "**Cenário Específico:** {context}\n\n"

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

                "### VARIEDADE ESTRUTURAL (OBRIGATÓRIO)\n"
                "Item legítimo PODE ter link (portal interno, aplicativo do banco, área do "
                "cliente) -- links.isEmpty não pode ser o que diferencia phishing de item "
                "legítimo. Varie entre os itens: alguns com link para canal próprio, outros "
                "só com instrução textual ('abra o app') ou telefone.\n\n"

                "### CARACTERÍSTICAS DOS NÍVEIS DE DIFICULDADE (para o item legítimo)\n"
                "Aqui, dificuldade não é 'quão convincente é o golpe' -- é 'quão fácil é o "
                "participante desconfiar sem motivo real' (o risco de falso alarme que este "
                "item testa):\n\n"

                "**FÁCIL:** sinais de confiança óbvios e numerosos -- domínio claramente "
                "oficial, saudação personalizada, nenhuma urgência, aviso de segurança explícito.\n\n"

                "**MÉDIO:** legítimo mas com algum elemento que poderia gerar dúvida à primeira "
                "vista (ex.: um prazo real e razoável, ou um assunto pouco comum mas verdadeiro), "
                "sem nunca cruzar para pedido de credencial ou link suspeito.\n\n"

                "**DIFÍCIL:** legítimo mas com elementos que SUPERFICIALMENTE lembram phishing "
                "(prazo apertado real, remetente de um setor incomum, assunto que soa urgente) "
                "-- o participante precisa checar os sinais de verdade (domínio, ausência de "
                "pedido de credencial, canal alternativo) para não cair em falso alarme.\n\n"

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
        self.website_llm = ChatOpenAI(
            model_name=model_name, api_key=api_key, temperature=0.7
        ).with_structured_output(WebsiteItemDraft)
        self.phone_call_llm = ChatOpenAI(
            model_name=model_name, api_key=api_key, temperature=0.7
        ).with_structured_output(PhoneCallItemDraft)
        self.pix_qr_llm = ChatOpenAI(
            model_name=model_name, api_key=api_key, temperature=0.7
        ).with_structured_output(PixQrItemDraft)
        # sms/whatsapp (issue #6, desbloqueados pela phishing-quest-api
        # #68): mesma separacao de LLM/prompt por canal dos 3 acima.
        self.sms_llm = ChatOpenAI(
            model_name=model_name, api_key=api_key, temperature=0.7
        ).with_structured_output(SmsItemDraft)
        self.whatsapp_llm = ChatOpenAI(
            model_name=model_name, api_key=api_key, temperature=0.7
        ).with_structured_output(WhatsAppItemDraft)

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
        self, difficulty: str, context: str, relevant_docs, is_malicious: bool = True
    ) -> GeneratedItemDraft:
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

        Returns:
            GeneratedItemDraft: NÃO inclui `nivel` nem `is_malicious`
            (ver issue #11 -- ambos são entrada da geração, não saída
            do LLM). `cues` já vem validado por `_validar_cues` (issue
            #5, passos 5 e 9) -- span incoerente é descartado (mantendo
            a pista) e item legítimo nunca sai daqui com pista alguma.
            `phish_scale` (issue #9) é montado por
            `_compute_phish_scale` a partir do `cues` já validado e do
            `premise_alignment` que o LLM julgou -- None para item
            legítimo.
        """
        chain = self.chain if is_malicious else self.legitimate_chain
        try:
            draft = await chain.ainvoke({
                "context": context,
                "difficulty": difficulty,
                "relevant_docs": relevant_docs
            })
        except Exception as e:
            logging.error(f"Error generating response: {e}")
            raise e

        draft.cues = self._validar_cues(draft.conteudo, draft.cues, is_malicious)
        draft.phish_scale = self._compute_phish_scale(draft.cues, draft.premise_alignment, is_malicious)
        return draft

    def _validar_cues(
        self, conteudo: str, cues: List[Cue], is_malicious: bool
    ) -> List[Cue]:
        """Aplica os passos 5 e 9 da issue #5 depois da geracao.

        Passo 9: item legitimo nunca deve ter pista de golpe. O prompt
        legitimo ja instrui `cues: []`, mas isso e disciplina de
        prompt, nao garantia -- aqui e onde a garantia de fato existe.
        Um LLM que "esquecer" a instrucao e descartado em silencio (com
        log), nao propagado: nao ha ganho em falhar a geracao inteira
        por causa de uma lista que deveria estar vazia.

        Passo 5: para cada pista de um item malicioso, confere que
        `conteudo[span_start:span_end]` bate exatamente com a
        `evidencia` declarada. Span incoerente (fora dos limites do
        texto ou trecho diferente) e zerado (vira None/None), mas a
        pista em si e MANTIDA -- o codigo da pista pode estar certo
        mesmo quando o modelo erra a localizacao exata, e um destaque
        errado no app e pior que nenhum destaque, nao pior que nenhuma
        pista.
        """
        if not is_malicious:
            if cues:
                logging.warning(
                    "LLM emitiu %d pista(s) de phishing num item legitimo -- "
                    "descartando (issue #5, passo 9).",
                    len(cues),
                )
            return []

        validadas = []
        for cue in cues:
            se_tem_span = cue.span_start is not None and cue.span_end is not None
            span_valido = (
                se_tem_span
                and 0 <= cue.span_start < cue.span_end <= len(conteudo)
                and conteudo[cue.span_start:cue.span_end] == cue.evidencia
            )
            if se_tem_span and not span_valido:
                cue = cue.model_copy(update={"span_start": None, "span_end": None})
            validadas.append(cue)
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
            return response.content.strip().strip('"')
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
                "Analise os documentos acadêmicos e extraia informações técnicas específicas para executar a tarefa solicitada.\n\n"
                
                "**TAREFA CRIATIVA:**\n"
                "{generation_context}\n\n"
                
                "**DOCUMENTOS ACADÊMICOS:**\n"
                "{full_context_text}\n\n"
                
                "**INSTRUÇÕES DE EXTRAÇÃO:**\n"
                "1. Identifique táticas, técnicas e métodos específicos relevantes para a tarefa\n"
                "2. Extraia gatilhos psicológicos e estratégias mencionadas\n"
                "3. Inclua exemplos práticos e terminologia técnica\n"
                "4. Mantenha apenas informações DIRETAMENTE úteis para a criação do email\n"
                "5. Organize em formato claro e acionável\n"
                "6. Relacione as técnicas com níveis de sofisticação (fácil, médio, difícil)\n\n"
                
                "**CONHECIMENTO TÉCNICO FOCADO (em português brasileiro):**"
            )
        )
        
        fusion_chain = prompt | self.text_llm
        
        try:
            response = await fusion_chain.ainvoke({
                "generation_context": generation_context,
                "full_context_text": full_context_text
            })
            return response.content.strip()
        except Exception as e:
            logging.error(f"Error fusing context: {e}")
            return full_context_text


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
            return response.content.strip()
        except Exception as e:
            logging.error(f"Error translating to English: {e}")
            return text