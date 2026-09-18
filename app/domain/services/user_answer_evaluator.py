# app/domain/services/user_answer_evaluator.py

import logging

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field


class UserAnswerScore(BaseModel):
    """Modelo estruturado para a resposta da avaliação"""
    score: int = Field(
        ge=0,
        le=5,
        description="Nota de 0 a 5 para a qualidade do raciocínio da justificativa"
    )
    feedback: str = Field(
        description="Feedback detalhado explicando a nota atribuída"
    )
    strengths: list[str] = Field(
        default_factory=list,
        description="Pontos fortes identificados na justificativa"
    )
    improvements: list[str] = Field(
        default_factory=list,
        description="Pontos que podem ser melhorados na justificativa"
    )
    # Campo aditivo (issue #4): a conclusao do usuario pode bater com o
    # rotulo verdadeiro por um argumento que nao sustenta essa
    # conclusao -- "acerto por sorte". Distinguir isso de competencia
    # de verdade e informacao valiosa para a pesquisa (issue #4 pede
    # para nao so rebaixar a nota silenciosamente, e sim marcar).
    acerto_por_sorte: bool = Field(
        default=False,
        description=(
            "True quando o veredito do usuário bate com o rótulo verdadeiro, "
            "mas a justificativa não sustenta essa conclusão (conclusão certa, "
            "argumento errado)."
        )
    )


class UserAnswerEvaluator:
    """
    Serviço para avaliar justificativas de usuários sobre identificação de phishing.

    Antes da issue #4, este serviço assumia -- no próprio prompt -- que
    o item apresentado era sempre phishing. Isso funcionava enquanto o
    corpus era 100% malicioso; com a #3 introduzindo itens legítimos,
    um usuário que acerta um item legítimo ("é confiável, domínio
    oficial, sem pedido de credencial") seria avaliado contra o
    critério errado e zerado -- ensinando exatamente o viés de falso
    alarme que o estudo quer medir.

    Agora avalia a QUALIDADE DO RACIOCÍNIO contra o rótulo verdadeiro e
    o veredito do usuário, cobrindo as quatro combinações possíveis
    (ver `_CASOS` abaixo), em vez de uma conclusão pré-definida.
    """

    def __init__(self, api_key: str, model_name: str = "gpt-4o-mini"):
        self.llm = ChatOpenAI(
            model_name=model_name,
            api_key=api_key,
            temperature=0.3
        ).with_structured_output(UserAnswerScore)

        self.logger = logging.getLogger(__name__)

    async def evaluate(
        self,
        item_content: str,
        is_malicious: bool,
        user_verdict: bool,
        user_justification: str,
    ) -> UserAnswerScore:
        """
        Avalia a justificativa do usuário sobre identificação de phishing.

        Args:
            item_content: O item (malicioso ou legítimo) apresentado ao usuário
            is_malicious: Rótulo VERDADEIRO do item (True = phishing, False = legítimo)
            user_verdict: O que o usuário respondeu (True = "é phishing", False = "é legítimo")
            user_justification: A justificativa do usuário para o veredito acima

        Returns:
            UserAnswerScore com nota de 0 a 5, feedback, e a sinalização de acerto por sorte
        """
        prompt = self._build_prompt(item_content, is_malicious, user_verdict, user_justification)

        try:
            result = await self.llm.ainvoke(prompt)
            acertou = is_malicious == user_verdict
            self.logger.info(
                f"Avaliação concluída: nota {result.score}/5 "
                f"(acertou={acertou}, acerto_por_sorte={result.acerto_por_sorte})"
            )
            return result
        except Exception as e:
            self.logger.error(f"Erro ao avaliar justificativa: {str(e)}")
            raise

    # As quatro combinacoes possiveis de rotulo verdadeiro x veredito
    # do usuario, com a instrucao especifica de cada caso (issue #4).
    # Chave: (is_malicious, user_verdict).
    _CASOS = {
        (True, True): (
            "ACERTOU EM ITEM MALICIOSO",
            "O usuário identificou corretamente que o item é phishing. Avalie QUAIS pistas "
            "reais presentes no item ele citou (typosquatting, urgência, pedido de "
            "credencial, etc.) e quais pistas presentes ele deixou passar. Nota alta exige "
            "citar pistas que realmente existem no item -- não basta acertar a conclusão."
        ),
        (True, False): (
            "ERROU EM ITEM MALICIOSO (falso negativo)",
            "O usuário não identificou um item que É phishing. Aponte, no feedback e em "
            "`improvements`, as pistas presentes no item que passaram batido. Não invente "
            "pista que não está no texto -- cite só o que está de fato presente."
        ),
        (False, False): (
            "ACERTOU EM ITEM LEGÍTIMO",
            "O usuário identificou corretamente que o item é legítimo (NÃO é phishing). "
            "Avalie se a justificativa cita sinais REAIS de legitimidade: domínio oficial, "
            "ausência de pedido de credencial, direcionamento a canal próprio, canal "
            "alternativo verificável. Nota alta exige citar esses sinais -- 'não achei nada "
            "suspeito' sem apontar um sinal positivo concreto é uma justificativa mais fraca."
        ),
        (False, True): (
            "ERROU EM ITEM LEGÍTIMO (falso alarme)",
            "O usuário identificou como phishing um item que é LEGÍTIMO. Isto é falso "
            "alarme, não acerto. Explique no feedback por que os elementos que o usuário "
            "citou como suspeitos NÃO são, de fato, indício de golpe neste item específico "
            "-- sem fingir que o item tinha uma pista de phishing que ele não tinha."
        ),
    }

    def _build_prompt(
        self, item_content: str, is_malicious: bool, user_verdict: bool, user_justification: str
    ) -> str:
        """Constrói o prompt para avaliação da justificativa"""
        nome_caso, instrucao_caso = self._CASOS[(is_malicious, user_verdict)]
        rotulo_real = "MALICIOSO (é phishing)" if is_malicious else "LEGÍTIMO (não é phishing)"
        veredito_texto = "que É phishing" if user_verdict else "que É legítimo"

        # Restricao que vale para TODOS os casos, mas e critica demais
        # para deixar implicita: no item legitimo, o feedback nunca
        # pode inventar um indicador de phishing que nao existe --
        # e exatamente o vies de falso alarme que a issue #4 existe
        # para eliminar.
        restricao_item_legitimo = (
            "\n\n## RESTRIÇÃO OBRIGATÓRIA\n"
            "Este item é LEGÍTIMO. O feedback e as listas de strengths/improvements NUNCA "
            "podem afirmar que existe um indicador de phishing, typosquatting, urgência "
            "maliciosa, remetente falso ou qualquer outra técnica de engenharia social neste "
            "item -- porque nenhuma delas existe aqui. Avalie apenas a qualidade do "
            "raciocínio sobre legitimidade."
            if not is_malicious
            else ""
        )

        return f"""## TAREFA
Você é um especialista em cibersegurança e educação. Sua tarefa é avaliar a QUALIDADE DO RACIOCÍNIO
de um usuário sobre um item que pode ser phishing ou uma comunicação legítima -- não apenas
verificar se ele chegou à conclusão certa.

## ITEM APRESENTADO AO USUÁRIO
{item_content}

## ROTULO VERDADEIRO (uso interno, não revelado ao usuário)
Este item é: {rotulo_real}

## VEREDITO DO USUÁRIO
O usuário respondeu {veredito_texto}.

## JUSTIFICATIVA DO USUÁRIO
{user_justification}

## CASO: {nome_caso}
{instrucao_caso}
{restricao_item_legitimo}

## ESCALA DE NOTAS (0-5) -- mede qualidade da argumentação, aplicável aos quatro casos

**Nota 0 - Incorreto:** Justificativa sem relação com o item apresentado, ou puramente aleatória.

**Nota 1 - Muito Fraco:** Menciona apenas um ponto superficial, sem embasar no conteúdo real do item.

**Nota 2 - Fraco:** Identifica poucos elementos de forma vaga; argumentação pouco desenvolvida.

**Nota 3 - Satisfatório:** Identifica alguns elementos corretos (pistas de phishing OU sinais de
legitimidade, conforme o caso); argumentação básica mas razoável.

**Nota 4 - Bom:** Identifica múltiplos elementos corretamente; boa articulação dos argumentos.

**Nota 5 - Excelente:** Identifica a maioria ou todos os elementos relevantes presentes no item;
argumentação clara, completa e bem estruturada.

## ACERTO POR SORTE
Marque `acerto_por_sorte=true` quando o veredito do usuário bater com o rótulo verdadeiro, mas a
justificativa não sustentar essa conclusão (ex.: disse "é phishing" corretamente, mas a razão dada
é genérica ou não corresponde a nada realmente presente no item). Isso é diferente de errar: é
acertar a conclusão por um argumento que não a sustenta. Se o veredito do usuário NÃO bateu com o
rótulo verdadeiro, `acerto_por_sorte` é sempre `false` (não se aplica a quem errou a conclusão).

## INSTRUÇÕES
1. Analise cuidadosamente o item apresentado
2. Compare com a justificativa do usuário, considerando o caso acima
3. Atribua uma nota de 0 a 5 pela QUALIDADE DO RACIOCÍNIO
4. Forneça feedback construtivo e específico ao item real
5. Liste pontos fortes e áreas de melhoria
6. Avalie se é acerto por sorte

Seja justo e educativo na avaliação."""
