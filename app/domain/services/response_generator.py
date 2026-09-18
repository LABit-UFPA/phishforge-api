# app/domain/services/response_generator.py

import logging
from langchain_core.prompts import PromptTemplate
from app.domain.models.generated_item_draft import GeneratedItemDraft
from langchain_openai import ChatOpenAI

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
                
                "### CARACTERÍSTICAS DOS NÍVEIS DE DIFICULDADE\n\n"
                
                "**FÁCIL:**\n"
                "- Remetente claramente suspeito ou genérico (ex: noreply@empresa123.com)\n"
                "- Assunto com erros ortográficos ou gramaticais evidentes\n"
                "- Urgência exagerada e óbvia ('URGENTE!!!', 'AÇÃO IMEDIATA')\n"
                "- Links visivelmente suspeitos ou encurtados\n"
                "- Formatação inconsistente ou amadora\n"
                "- Ausência de personalização (tratamento genérico)\n"
                "- Ameaças diretas e explícitas\n"
                "- Solicitação óbvia de informações sensíveis\n\n"
                
                "**MÉDIO:**\n"
                "- Remetente parcialmente convincente mas com pequenas inconsistências\n"
                "- Assunto plausível mas com alguns indicadores de suspeita\n"
                "- Urgência moderada com justificativa aparente\n"
                "- Links que parecem legítimos à primeira vista\n"
                "- Formatação mais profissional, similar a comunicações empresariais\n"
                "- Personalização básica (nome do destinatário)\n"
                "- Mistura de informações verdadeiras com falsas\n"
                "- Uso de logos e identidade visual parcialmente convincentes\n"
                "- Solicitação indireta de ação (download, clique, verificação)\n\n"
                
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
                "- Engenharia social sofisticada (psicologia, autoridade, reciprocidade)\n\n"
                
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
                "- ✓ Coerência entre cenário + táticas + nível?\n\n"
                
                "## FORMATO DE RESPOSTA\n"
                "Gere APENAS o objeto JSON com os campos solicitados (receptor, remetente, assunto, conteudo, explicacao, categoria, links).\n"
                "Não mostre explicitamente os passos de raciocínio, mas seu resultado deve demonstrar que você seguiu o processo Chain-of-Thought, implementando:\n"
                "- As características específicas do nível '{difficulty}'\n"
                "- As táticas acadêmicas do conhecimento técnico\n"
                "- O cenário solicitado de forma completa e precisa\n"
                "- Raciocínio coerente e fundamentado em cada elemento"
            )
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
        self.hyde_chain = self.hyde_prompt_template | self.text_llm

    async def generate_response(self, difficulty: str, context: str, relevant_docs) -> GeneratedItemDraft:
        """
        Gera um email de phishing baseado no contexto, dificuldade e documentos relevantes.

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

        Returns:
            GeneratedItemDraft: NÃO inclui `nivel` (ver issue #11 --
            dificuldade é entrada da geração, não saída do LLM). Quem
            chama esta função monta o `PhishingEmail` final combinando
            o draft com o `difficulty` acima.
        """
        try:
            return await self.chain.ainvoke({
                "context": context,
                "difficulty": difficulty,
                "relevant_docs": relevant_docs
            })
        except Exception as e:
            logging.error(f"Error generating response: {e}")
            raise e

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