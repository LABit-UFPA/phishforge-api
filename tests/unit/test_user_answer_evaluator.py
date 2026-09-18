"""Teste direto de UserAnswerEvaluator._build_prompt (issue #4), sem
LLM: garante que as quatro combinacoes rotulo x veredito produzem
instrucao especifica, e que a restricao central da issue -- nunca
inventar indicador de phishing num item legitimo -- so aparece quando
o item e de fato legitimo.
"""

from app.domain.services.user_answer_evaluator import UserAnswerEvaluator


def _build_evaluator():
    return UserAnswerEvaluator(api_key="sk-nao-usada-neste-teste")


def test_malicioso_acertou_pede_pistas_identificadas():
    evaluator = _build_evaluator()
    prompt = evaluator._build_prompt("item", is_malicious=True, user_verdict=True, user_justification="x")
    assert "ACERTOU EM ITEM MALICIOSO" in prompt
    assert "passaram batido" not in prompt  # texto especifico do caso ERROU


def test_malicioso_errou_pede_pistas_que_passaram_batido():
    evaluator = _build_evaluator()
    prompt = evaluator._build_prompt("item", is_malicious=True, user_verdict=False, user_justification="x")
    assert "ERROU EM ITEM MALICIOSO" in prompt
    assert "falso negativo" in prompt


def test_legitimo_acertou_pede_sinais_de_legitimidade():
    evaluator = _build_evaluator()
    prompt = evaluator._build_prompt("item", is_malicious=False, user_verdict=False, user_justification="x")
    assert "ACERTOU EM ITEM LEGÍTIMO" in prompt
    assert "sinais REAIS de legitimidade" in prompt


def test_legitimo_errou_e_falso_alarme_nao_acerto():
    evaluator = _build_evaluator()
    prompt = evaluator._build_prompt("item", is_malicious=False, user_verdict=True, user_justification="x")
    assert "falso alarme" in prompt
    assert "ERROU EM ITEM LEGÍTIMO" in prompt


def test_restricao_contra_inventar_phishing_so_aparece_em_item_legitimo():
    """Este e o criterio central da issue #4: o feedback nunca pode
    afirmar que existe indicador de phishing num item legitimo. A
    restricao precisa estar no prompt sempre que is_malicious=False,
    e nao precisa estar quando is_malicious=True (o item malicioso tem
    pistas de verdade, entao a restricao nao se aplica).
    """
    evaluator = _build_evaluator()

    prompt_legitimo_acertou = evaluator._build_prompt(
        "item", is_malicious=False, user_verdict=False, user_justification="x"
    )
    prompt_legitimo_errou = evaluator._build_prompt(
        "item", is_malicious=False, user_verdict=True, user_justification="x"
    )
    prompt_malicioso = evaluator._build_prompt(
        "item", is_malicious=True, user_verdict=True, user_justification="x"
    )

    restricao = "NUNCA podem afirmar que existe um indicador de phishing"
    assert restricao in prompt_legitimo_acertou
    assert restricao in prompt_legitimo_errou
    assert restricao not in prompt_malicioso
