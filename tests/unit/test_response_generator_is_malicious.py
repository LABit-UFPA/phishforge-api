"""Prova de que `is_malicious` seleciona a chain correta em
ResponseGenerator (issue #3): duas chains distintas, com objetivos
opostos, nao uma so com uma flag no meio do prompt.

Constroi um ResponseGenerator real (a construcao so monta objetos
LangChain, nao faz chamada de rede) e substitui `.chain`/
`.legitimate_chain` por fakes registrando quem foi invocado -- sem
isso, so testar via HTTP com FakeResponseGenerator nao provaria nada
sobre a selecao de chain, porque o fake reimplementa o metodo inteiro.
"""

from app.domain.services.response_generator import ResponseGenerator


class _ChainEspiao:
    def __init__(self, nome):
        self.nome = nome
        self.invocado_com = None

    async def ainvoke(self, args):
        self.invocado_com = args
        return "resultado fake"


def _build_generator_com_chains_espias():
    generator = ResponseGenerator(api_key="sk-nao-usada-neste-teste")
    generator.chain = _ChainEspiao("phishing")
    generator.legitimate_chain = _ChainEspiao("legitimo")
    return generator


async def test_is_malicious_true_usa_a_chain_de_phishing():
    generator = _build_generator_com_chains_espias()

    await generator.generate_response(
        difficulty="facil", context="ctx", relevant_docs="docs", is_malicious=True
    )

    assert generator.chain.invocado_com is not None
    assert generator.legitimate_chain.invocado_com is None


async def test_is_malicious_false_usa_a_chain_legitima():
    generator = _build_generator_com_chains_espias()

    await generator.generate_response(
        difficulty="facil", context="ctx", relevant_docs="docs", is_malicious=False
    )

    assert generator.legitimate_chain.invocado_com is not None
    assert generator.chain.invocado_com is None


async def test_is_malicious_default_e_true():
    """Retrocompatibilidade: chamador antigo que nao passa is_malicious
    continua gerando phishing.
    """
    generator = _build_generator_com_chains_espias()

    await generator.generate_response(difficulty="facil", context="ctx", relevant_docs="docs")

    assert generator.chain.invocado_com is not None
    assert generator.legitimate_chain.invocado_com is None


def test_prompt_legitimo_nao_pede_credencial_e_o_de_phishing_nao_promete_isso():
    """Sanidade textual dos dois prompts, sem chamar LLM nenhum: o
    prompt legitimo instrui a NUNCA pedir credencial; o de phishing nao
    tem essa mesma restricao (ele existe para simular exatamente isso).
    """
    generator = ResponseGenerator(api_key="sk-nao-usada-neste-teste")

    texto_legitimo = generator.legitimate_prompt_template.template
    texto_phishing = generator.prompt_template.template

    assert "NUNCA pede senha" in texto_legitimo
    assert "canal alternativo" in texto_legitimo
    assert "NUNCA pede senha" not in texto_phishing
